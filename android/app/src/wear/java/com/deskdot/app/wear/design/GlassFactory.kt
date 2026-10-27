package com.deskdot.app.wear.design

import android.graphics.Bitmap
import android.graphics.BlurMaskFilter
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.util.LruCache
import androidx.compose.runtime.Immutable
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.toArgb

/**
 * §1.9 "Liquid glass on Adreno 504". Every element is rendered ONCE into an ARGB_8888 bitmap with a
 * software Canvas and drawn at runtime with a single drawImage. Layers follow the spec and the
 * approved preview's `glass()` exactly:
 *  G0 drop shadow (only when [GlassKey.shadow]; overlays over content, §4.7),
 *  (accent/error: #000 @ 20% base + optional solid fill @ 85%),
 *  G2 body tint, G3 top lensing highlight, G4 bottom inner shadow, G5 specular rim (2 px, inset 1),
 *  G7 text plate for *-text variants and the lens.
 * Gradients use the SVG objectBoundingBox geometry the preview uses (unit gradients scaled by the
 * element's w x h), so non-square elements (lens, pills) match the preview's skewed rim/highlight.
 * G1 (backdrop lens) and G6 (bright-backdrop hairline) only apply over the Liquid face's aurora and
 * are never needed on Suite's black backdrop.
 */
enum class GlassVariant {
    Neutral, NeutralText, Accent, AccentText, Lens, Error, ErrorText, SunText;

    val hasPlate get() = this == NeutralText || this == AccentText || this == Lens || this == ErrorText || this == SunText
}

@Immutable
data class GlassKey(
    val w: Int,
    val h: Int,
    val radius: Float,
    val variant: GlassVariant,
    /** accent colour for Accent* variants (ignored otherwise; normalise to 0 for cache hits). */
    val accentArgb: Int = 0,
    /** accent-light for the rim of Accent* variants. */
    val accentLightArgb: Int = 0,
    /** Solid fill under the body (accent @ 85% for "on" toggles and the accent picker). */
    val fill: Boolean = false,
    val shadow: Boolean = false,
)

class GlassImage(val image: ImageBitmap, val pad: Int, val byteCount: Int)

object GlassFactory {
    private const val SHADOW_PAD = 20

    private val cache = object : LruCache<GlassKey, GlassImage>(3 * 1024 * 1024) {
        override fun sizeOf(key: GlassKey, value: GlassImage): Int = value.byteCount
    }

    fun get(key: GlassKey): GlassImage {
        cache.get(key)?.let { return it }
        val img = render(key)
        cache.put(key, img)
        return img
    }

    /** Off-main-thread warm-up of the bitmaps the first screens need. */
    fun prewarm(keys: List<GlassKey>) {
        keys.forEach { if (cache.get(it) == null) cache.put(it, render(it)) }
    }

    fun trim() = cache.evictAll()

    fun accentKey(w: Int, h: Int, r: Float, roles: AccentRoles, fill: Boolean, text: Boolean = false, shadow: Boolean = false) =
        GlassKey(
            w, h, r, if (text) GlassVariant.AccentText else GlassVariant.Accent,
            roles.accent.toArgb(), roles.accentLight.toArgb(), fill, shadow,
        )

    private fun a(alpha: Float, rgb: Int): Int = ((alpha * 255f + 0.5f).toInt().coerceIn(0, 255) shl 24) or (rgb and 0xFFFFFF)

    private fun render(k: GlassKey): GlassImage {
        val pad = if (k.shadow) SHADOW_PAD else 0
        val bw = k.w + pad * 2
        val bh = k.h + pad * 2
        val bmp = Bitmap.createBitmap(bw, bh, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        val w = k.w.toFloat()
        val h = k.h.toFloat()
        val r = k.radius.coerceAtMost(minOf(w, h) / 2f)
        val p = Paint(Paint.ANTI_ALIAS_FLAG)

        if (k.shadow) {
            // G0: shape offset +6 px, blur 16 px (the preview's stdDeviation 8), #000 @ 55%.
            val sp = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = a(0.55f, 0)
                maskFilter = BlurMaskFilter(16f, BlurMaskFilter.Blur.NORMAL)
            }
            c.drawRoundRect(RectF(pad.toFloat(), pad + 6f, pad + w, pad + 6f + h), r, r, sp)
        }
        c.translate(pad.toFloat(), pad.toFloat())
        val shape = RectF(0f, 0f, w, h)

        val isAccent = k.variant == GlassVariant.Accent || k.variant == GlassVariant.AccentText
        val isError = k.variant == GlassVariant.Error || k.variant == GlassVariant.ErrorText
        val tint = when {
            isError -> 0xFFFF5A5F.toInt()
            isAccent -> k.accentArgb
            else -> 0xFFFFFFFF.toInt()
        }

        if (isAccent || isError) {
            p.color = a(0.20f, 0)
            c.drawRoundRect(shape, r, r, p)
        }
        if (k.fill) {
            p.color = a(0.85f, tint)
            c.drawRoundRect(shape, r, r, p)
        }

        // A Paint's colour alpha multiplies its shader: reset it after the solid base/fill layers above,
        // otherwise every shader layer of accent/error glass is drawn at 20 % (or 85 %) strength.
        p.color = 0xFF000000.toInt()
        // G2 body: vertical gradient over the element's bounding box.
        val (top, bottom) = when (k.variant) {
            GlassVariant.Lens -> 0.07f to 0.03f
            GlassVariant.SunText -> 0.22f to 0.14f
            GlassVariant.Accent, GlassVariant.AccentText, GlassVariant.Error, GlassVariant.ErrorText -> 0.30f to 0.16f
            else -> 0.12f to 0.05f
        }
        p.shader = LinearGradient(0f, 0f, 0f, h, a(top, tint), a(bottom, tint), Shader.TileMode.CLAMP)
        c.drawRoundRect(shape, r, r, p)

        // G3 top lensing highlight: radial at (0.5, 0.18), radii (0.48 w, 0.36 h) — objectBoundingBox.
        val lens = k.variant == GlassVariant.Lens
        val peak = if (lens) 0.16f else 0.22f
        val mid = if (lens) 0.05f else 0.08f
        val hi = RadialGradient(
            0f, 0f, 1f,
            intArrayOf(a(peak, -1), a(mid, -1), a(0f, -1)),
            floatArrayOf(0f, 0.55f, 1f), Shader.TileMode.CLAMP,
        )
        hi.setLocalMatrix(Matrix().apply { setScale(0.48f * w, 0.36f * h); postTranslate(0.5f * w, 0.18f * h) })
        p.shader = hi
        c.drawRoundRect(shape, r, r, p)

        // G4 bottom inner shadow: y 0.62 h -> h, #000 0% -> 22%.
        p.shader = LinearGradient(0f, 0.62f * h, 0f, h, a(0f, 0), a(0.22f, 0), Shader.TileMode.CLAMP)
        c.drawRoundRect(shape, r, r, p)

        // G5 specular rim: 2 px stroke inset 1 px, diagonal gradient in bounding-box space.
        val rimEnd = when {
            isAccent -> k.accentLightArgb
            isError -> 0xFFFF9A9D.toInt()
            else -> -1
        }
        val rim = LinearGradient(
            0f, 0f, 1f, 1f,
            intArrayOf(a(0.70f, rimEnd), a(0.22f, -1), a(0.06f, -1), a(0.12f, -1), a(0.38f, rimEnd)),
            floatArrayOf(0f, 0.30f, 0.55f, 0.80f, 1f), Shader.TileMode.CLAMP,
        )
        rim.setLocalMatrix(Matrix().apply { setScale(w, h) })
        p.shader = rim
        p.style = Paint.Style.STROKE
        p.strokeWidth = 2f
        val rr = (r - 1f).coerceAtLeast(0f)
        c.drawRoundRect(RectF(1f, 1f, w - 1f, h - 1f), rr, rr, p)
        p.style = Paint.Style.FILL
        p.shader = null

        // G7 text plate: inset 4, radius r - 4.
        if (k.variant.hasPlate) {
            val plate = when (k.variant) {
                GlassVariant.Lens -> 0.35f
                GlassVariant.SunText -> 0.55f
                else -> 0.45f
            }
            p.color = a(plate, 0)
            val pr = (r - 4f).coerceAtLeast(0f)
            c.drawRoundRect(RectF(4f, 4f, w - 4f, h - 4f), pr, pr, p)
        }
        bmp.prepareToDraw()
        return GlassImage(bmp.asImageBitmap(), pad, bmp.byteCount)
    }
}

/** Draws cached glass with its element top-left at ([x], [y]). One drawImage. */
fun DrawScope.drawGlass(glass: GlassImage, x: Float, y: Float, alpha: Float = 1f) {
    if (alpha <= 0.002f) return
    drawImage(glass.image, Offset(x - glass.pad, y - glass.pad), alpha = alpha)
}
