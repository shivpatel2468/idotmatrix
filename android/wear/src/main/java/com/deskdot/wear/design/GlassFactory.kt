package com.deskdot.wear.design

import android.graphics.Bitmap
import android.graphics.BlurMaskFilter
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PorterDuff
import android.graphics.PorterDuffXfermode
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.util.LruCache
import androidx.compose.runtime.Immutable
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.withTransform
import com.deskdot.wear.theme.WatchPalette
import com.deskdot.wear.theme.WatchThemes

/**
 * Copied from the Orbit launcher (gen6-watch launcher/.../design/GlassFactory.kt) so DeskDot on the watch wears the
 * same glass. Glass v2 (DESIGN_SPEC Rev 2): liquid glass that reads as an object on OLED black (and on the
 * light mode's porcelain), in the active table's colours. Every element is rendered ONCE into an
 * ARGB_8888 bitmap with a software Canvas, cached by (size, variant, table, dark, shadow), and drawn
 * at runtime with a single drawImage. Nothing here runs per frame.
 *
 * Layers, bottom to top (raised glass):
 *  1. baked drop shadow — floating chrome only ([GlassKey.shadow]: menu buttons, the brightness bead);
 *  2. tinted body — a vertical gradient from the table's glass/chassis tones (accent-deep when "on"),
 *     opaque, so text on it always sits on a solid plate;
 *  3. felt tint — the table's felt (accent when "on") glowing up from the bottom, faint;
 *  4. inner accent glow — "on" variants only, a blurred accent band just inside the rim;
 *  5. inner bottom shade;
 *  6. top sheen — a curved gloss cap plus a small specular spot at the top-left;
 *  7. lit hairline rim — glass-rim (bright, top-left) → glass-edge → the accent at the bottom-right,
 *     with a second faint inner hairline at the top for thickness and a thin accent caustic at the
 *     bottom.
 * [GlassVariant.Well] is the inverse (a recessed key-floor well: inner top shadow, lit lower lip),
 * [GlassVariant.Bead] a small domed glass bead, and [GlassVariant.Glow] a soft accent bloom.
 */
enum class GlassVariant {
    Neutral, NeutralText, SunText, On, Lens, Error, ErrorText, Well, Bead, Glow,

    /** Owner Rev 2.2: glass only on the border (a band with lit rims); the middle stays clear, so nothing covers the app. */
    Frame;

    val text get() = this == NeutralText || this == SunText || this == ErrorText
}

@Immutable
data class GlassKey(
    val w: Int,
    val h: Int,
    val radius: Float,
    val variant: GlassVariant,
    val table: String = WatchThemes.DEFAULT,
    val dark: Boolean = true,
    val shadow: Boolean = false,
)

class GlassImage(val image: ImageBitmap, val pad: Int, val byteCount: Int)

object GlassFactory {
    private const val SHADOW_PAD = 24

    private val cache = object : LruCache<GlassKey, GlassImage>(4 * 1024 * 1024) {
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

    /** For tests: how many bitmaps are cached (proves the cache is hit, not re-rendered). */
    /** Number of baked images (LruCache.size() is in bytes here, because sizeOf is overridden). */
    internal fun cachedCount(): Int = cache.snapshot().size

    private fun a(alpha: Float, rgb: Int): Int = ((alpha * 255f + 0.5f).toInt().coerceIn(0, 255) shl 24) or (rgb and 0xFFFFFF)

    private fun mix(x: Int, y: Int, t: Float): Int {
        fun ch(s: Int) = (((x shr s) and 255) + ((((y shr s) and 255) - ((x shr s) and 255)) * t)).toInt().coerceIn(0, 255)
        return (ch(24) shl 24) or (ch(16) shl 16) or (ch(8) shl 8) or ch(0)
    }

    private const val WHITE = -1
    private const val BLACK = 0xFF000000.toInt()
    private const val ERR = 0xFFFF5A5F.toInt()

    /** The colours one variant needs, resolved from the table palette. */
    private class Tones(
        val top: Int, val bottom: Int, val tint: Int, val tintA: Float,
        val rimHi: Int, val rimMid: Float, val rimLo: Int, val caustic: Int,
        val sheenTop: Float, val sheenBottom: Float, val spot: Float, val shade: Float,
        val glow: Int, val glowA: Float,
    )

    private fun tones(v: GlassVariant, p: WatchPalette, dark: Boolean): Tones {
        val accent = if (v == GlassVariant.Error || v == GlassVariant.ErrorText) (if (dark) ERR else 0xFFC8343A.toInt()) else p.accent
        val deep = if (v == GlassVariant.Error || v == GlassVariant.ErrorText) (if (dark) 0xFF3A0E10.toInt() else 0xFFFFE6E6.toInt()) else p.accentDeep
        val rimLight = a(if (dark) 1f else 1f, if (dark) p.glassRim else WHITE)
        val edge = a(if (dark) 0.75f else 0.42f, if (dark) accent else p.metal)
        return if (dark) when (v) {
            GlassVariant.On, GlassVariant.Error, GlassVariant.ErrorText -> Tones(
                top = mix(deep, accent, 0.16f), bottom = mix(deep, BLACK, 0.35f), tint = accent, tintA = 0.26f,
                rimHi = a(0.95f, mix(accent, WHITE, 0.45f)), rimMid = 0.30f, rimLo = a(0.85f, accent), caustic = a(0.55f, accent),
                sheenTop = 0.20f, sheenBottom = 0.03f, spot = 0.20f, shade = 0.40f, glow = accent, glowA = 0.42f,
            )
            GlassVariant.Lens -> Tones(
                top = mix(p.glass, p.chassis4, 0.85f), bottom = mix(p.glass, BLACK, 0.25f), tint = p.felt, tintA = 0.55f,
                rimHi = rimLight, rimMid = 0.30f, rimLo = edge, caustic = a(0.55f, accent),
                sheenTop = 0.24f, sheenBottom = 0.03f, spot = 0.18f, shade = 0.45f, glow = 0, glowA = 0f,
            )
            GlassVariant.SunText -> Tones(
                top = p.chassis4, bottom = p.chassis2, tint = p.felt, tintA = 0.25f,
                rimHi = rimLight, rimMid = 0.22f, rimLo = edge, caustic = a(0.30f, accent),
                sheenTop = 0.10f, sheenBottom = 0.02f, spot = 0.08f, shade = 0.30f, glow = 0, glowA = 0f,
            )
            GlassVariant.NeutralText -> Tones(
                top = mix(p.glass, p.chassis4, 0.85f), bottom = mix(p.glass, BLACK, 0.15f), tint = p.felt, tintA = 0.42f,
                rimHi = rimLight, rimMid = 0.30f, rimLo = edge, caustic = a(0.50f, accent),
                sheenTop = 0.22f, sheenBottom = 0.03f, spot = 0.18f, shade = 0.40f, glow = 0, glowA = 0f,
            )
            GlassVariant.Bead -> Tones(
                top = mix(p.chassis4, WHITE, 0.10f), bottom = mix(p.glass, BLACK, 0.2f), tint = p.felt, tintA = 0.30f,
                rimHi = a(0.95f, p.glassRim), rimMid = 0.25f, rimLo = a(0.70f, accent), caustic = a(0.45f, accent),
                sheenTop = 0.34f, sheenBottom = 0.05f, spot = 0.30f, shade = 0.45f, glow = 0, glowA = 0f,
            )
            else -> Tones(
                top = mix(p.chassis3, p.chassis4, 0.6f), bottom = mix(p.glass, BLACK, 0.15f), tint = p.felt, tintA = 0.45f,
                rimHi = rimLight, rimMid = 0.32f, rimLo = edge, caustic = a(0.50f, accent),
                sheenTop = 0.30f, sheenBottom = 0.04f, spot = 0.24f, shade = 0.42f, glow = 0, glowA = 0f,
            )
        } else when (v) {
            GlassVariant.On, GlassVariant.Error, GlassVariant.ErrorText -> Tones(
                top = mix(deep, WHITE, 0.5f), bottom = mix(deep, accent, 0.16f), tint = accent, tintA = 0.14f,
                rimHi = a(1f, WHITE), rimMid = 0.6f, rimLo = a(0.85f, accent), caustic = a(0.40f, accent),
                sheenTop = 0.80f, sheenBottom = 0.10f, spot = 0.6f, shade = 0.06f, glow = accent, glowA = 0.22f,
            )
            GlassVariant.Bead -> Tones(
                top = WHITE, bottom = mix(p.chassis1, p.chassis4, 0.5f), tint = p.felt, tintA = 0.06f,
                rimHi = a(1f, WHITE), rimMid = 0.7f, rimLo = a(0.55f, p.metal), caustic = a(0.30f, p.metal),
                sheenTop = 0.9f, sheenBottom = 0.2f, spot = 0.8f, shade = 0.10f, glow = 0, glowA = 0f,
            )
            else -> Tones(
                top = mix(p.chassis2, WHITE, 0.6f), bottom = mix(p.chassis1, p.chassis4, 0.55f), tint = p.felt, tintA = 0.08f,
                rimHi = rimLight, rimMid = 0.65f, rimLo = edge, caustic = a(0.22f, p.metal),
                sheenTop = 0.85f, sheenBottom = 0.12f, spot = 0.7f, shade = 0.07f, glow = 0, glowA = 0f,
            )
        }
    }

    private fun render(k: GlassKey): GlassImage {
        val pal = WatchThemes.get(k.table).palette(k.dark)
        val pad = if (k.shadow) SHADOW_PAD else 0
        val bmp = Bitmap.createBitmap(k.w + pad * 2, k.h + pad * 2, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        val w = k.w.toFloat()
        val h = k.h.toFloat()
        val r = k.radius.coerceAtMost(minOf(w, h) / 2f)
        val p = Paint(Paint.ANTI_ALIAS_FLAG)

        if (k.variant == GlassVariant.Frame) {
            renderFrame(c, w, h, r, pal, k.dark)
            bmp.prepareToDraw()
            return GlassImage(bmp.asImageBitmap(), 0, bmp.byteCount)
        }

        if (k.variant == GlassVariant.Glow) {
            val col = if (k.dark) pal.accent2 else pal.accent
            p.shader = RadialGradient(
                w / 2f, h / 2f, minOf(w, h) / 2f,
                intArrayOf(a(if (k.dark) 0.60f else 0.35f, col), a(if (k.dark) 0.20f else 0.12f, col), a(0f, col)),
                floatArrayOf(0f, 0.42f, 1f), Shader.TileMode.CLAMP,
            )
            c.drawRect(0f, 0f, w, h, p)
            bmp.prepareToDraw()
            return GlassImage(bmp.asImageBitmap(), 0, bmp.byteCount)
        }

        if (k.shadow) {
            val sp = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = if (k.dark) a(0.80f, 0) else a(0.20f, 0x2A2420)
                maskFilter = BlurMaskFilter(if (k.dark) 16f else 12f, BlurMaskFilter.Blur.NORMAL)
            }
            val dy = if (k.dark) 8f else 5f
            c.drawRoundRect(RectF(pad.toFloat() + 2f, pad + dy, pad + w - 2f, pad + dy + h), r, r, sp)
        }
        c.translate(pad.toFloat(), pad.toFloat())
        val shape = RectF(0f, 0f, w, h)
        val atop = PorterDuffXfermode(PorterDuff.Mode.SRC_ATOP)

        if (k.variant == GlassVariant.Well) {
            renderWell(c, p, shape, r, pal, k.dark, atop)
            bmp.prepareToDraw()
            return GlassImage(bmp.asImageBitmap(), pad, bmp.byteCount)
        }

        val t = tones(k.variant, pal, k.dark)
        val layer = c.saveLayer(shape, null)

        // 2. body
        if (k.variant == GlassVariant.Bead) {
            p.shader = RadialGradient(
                0.38f * w, 0.30f * h, maxOf(w, h) * 0.85f,
                intArrayOf(t.top, mix(t.top, t.bottom, 0.55f), t.bottom), floatArrayOf(0f, 0.5f, 1f), Shader.TileMode.CLAMP,
            )
        } else {
            p.shader = LinearGradient(0f, 0f, 0f, h, t.top, t.bottom, Shader.TileMode.CLAMP)
        }
        c.drawRoundRect(shape, r, r, p)
        p.xfermode = atop

        // 3. felt (or accent) tint rising from the bottom
        if (t.tintA > 0f) {
            val tint = RadialGradient(0f, 0f, 1f, intArrayOf(a(t.tintA, t.tint), a(0f, t.tint)), null, Shader.TileMode.CLAMP)
            tint.setLocalMatrix(Matrix().apply { setScale(0.75f * w, 0.85f * h); postTranslate(0.5f * w, 1.08f * h) })
            p.shader = tint
            c.drawRect(shape, p)
        }

        // 4. inner accent glow ("on")
        if (t.glowA > 0f) {
            val g = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                style = Paint.Style.STROKE
                strokeWidth = minOf(w, h) * 0.16f
                color = a(t.glowA, t.glow)
                maskFilter = BlurMaskFilter(minOf(w, h) * 0.12f, BlurMaskFilter.Blur.NORMAL)
                xfermode = atop
            }
            c.drawRoundRect(shape, r, r, g)
        }

        // 5. inner bottom shade
        p.shader = LinearGradient(0f, 0.55f * h, 0f, h, a(0f, 0), a(t.shade, 0), Shader.TileMode.CLAMP)
        c.drawRect(shape, p)

        // 6. top sheen: a curved gloss cap + a specular spot
        val cap = RectF(-0.18f * w, -0.62f * h, 1.18f * w, 0.50f * h)
        p.shader = LinearGradient(0f, 0f, 0f, 0.50f * h, a(t.sheenTop, WHITE), a(t.sheenBottom, WHITE), Shader.TileMode.CLAMP)
        c.drawOval(cap, p)
        val spot = RadialGradient(0f, 0f, 1f, intArrayOf(a(t.spot, WHITE), a(0f, WHITE)), null, Shader.TileMode.CLAMP)
        val sr = minOf(w, h)
        spot.setLocalMatrix(Matrix().apply { setScale(0.30f * sr, 0.20f * sr); postTranslate(minOf(0.30f * w, 0.42f * sr + r * 0.2f), 0.20f * h) })
        p.shader = spot
        c.drawRect(shape, p)
        p.xfermode = null
        c.restoreToCount(layer)

        // 7. rims
        drawRims(c, w, h, r, t, k.dark)
        bmp.prepareToDraw()
        return GlassImage(bmp.asImageBitmap(), pad, bmp.byteCount)
    }

    private fun drawRims(c: Canvas, w: Float, h: Float, r: Float, t: Tones, dark: Boolean) {
        val p = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
        // Lit hairline rim: bright at the top-left, clear through the middle, the accent at the bottom-right.
        val rim = LinearGradient(
            0f, 0f, 1f, 1f,
            intArrayOf(t.rimHi, a(t.rimMid, WHITE), a(t.rimMid * 0.3f, WHITE), t.rimLo),
            floatArrayOf(0f, 0.38f, 0.62f, 1f), Shader.TileMode.CLAMP,
        )
        rim.setLocalMatrix(Matrix().apply { setScale(w, h) })
        p.shader = rim
        p.strokeWidth = 2.75f
        val i1 = 0.875f
        c.drawRoundRect(RectF(i1, i1, w - i1, h - i1), (r - i1).coerceAtLeast(0f), (r - i1).coerceAtLeast(0f), p)

        // Inner hairline at the top: gives the glass a thickness.
        p.shader = LinearGradient(0f, 0f, 0f, h * 0.45f, a(if (dark) 0.16f else 0.9f, WHITE), a(0f, WHITE), Shader.TileMode.CLAMP)
        p.strokeWidth = 1f
        val i2 = 2.75f
        c.drawRoundRect(RectF(i2, i2, w - i2, h - i2), (r - i2).coerceAtLeast(0f), (r - i2).coerceAtLeast(0f), p)

        // Caustic: the accent catching the lower inside edge.
        p.shader = LinearGradient(0f, h * 0.62f, 0f, h, t.caustic and 0x00FFFFFF, t.caustic, Shader.TileMode.CLAMP)
        p.strokeWidth = 2f
        val i3 = 2.4f
        c.drawRoundRect(RectF(i3, i3, w - i3, h - i3), (r - i3).coerceAtLeast(0f), (r - i3).coerceAtLeast(0f), p)
    }

    /** A recessed well (the brightness track, switch tracks): key-floor fill, inner top shadow, lit lower lip. */
    private fun renderWell(c: Canvas, p: Paint, shape: RectF, r: Float, pal: WatchPalette, dark: Boolean, atop: PorterDuffXfermode) {
        val w = shape.width()
        val h = shape.height()
        val layer = c.saveLayer(shape, null)
        p.shader = LinearGradient(
            0f, 0f, 0f, h,
            if (dark) pal.keyFloor else mix(pal.keyFloor, BLACK, 0.06f),
            if (dark) mix(pal.keyFloor, pal.chassis2, 0.55f) else mix(pal.keyFloor, WHITE, 0.25f),
            Shader.TileMode.CLAMP,
        )
        c.drawRoundRect(shape, r, r, p)
        p.shader = null
        p.xfermode = atop
        // Inner shadow from the top edge.
        val sh = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = h * 0.35f
            color = a(if (dark) 0.85f else 0.22f, 0)
            maskFilter = BlurMaskFilter(h * 0.18f, BlurMaskFilter.Blur.NORMAL)
            xfermode = atop
        }
        c.save()
        c.translate(0f, h * 0.10f)
        c.drawRoundRect(RectF(-2f, -2f, w + 2f, h + 2f), r, r, sh)
        c.restore()
        // A faint felt floor.
        val tint = RadialGradient(0f, 0f, 1f, intArrayOf(a(if (dark) 0.22f else 0.06f, pal.felt), a(0f, pal.felt)), null, Shader.TileMode.CLAMP)
        tint.setLocalMatrix(Matrix().apply { setScale(0.6f * w, 1.2f * h); postTranslate(0.5f * w, 1.1f * h) })
        p.shader = tint
        c.drawRect(shape, p)
        p.xfermode = null
        p.shader = null
        c.restoreToCount(layer)
        // Rim: dark at the top (the lip that casts the shadow), lit along the bottom (the far wall catching light).
        val rim = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeWidth = 1.5f
            shader = LinearGradient(
                0f, 0f, 0f, h,
                intArrayOf(a(if (dark) 0.9f else 0.35f, if (dark) BLACK else pal.line2), a(if (dark) 0.10f else 0.2f, WHITE), a(if (dark) 0.42f else 1f, if (dark) pal.glassRim else WHITE)),
                floatArrayOf(0f, 0.5f, 1f), Shader.TileMode.CLAMP,
            )
        }
        c.drawRoundRect(RectF(0.75f, 0.75f, w - 0.75f, h - 0.75f), r - 0.75f, r - 0.75f, rim)
    }

    /** A glass border band: [BAND] px of tinted glass with a lit outer rim and a fine inner rim; transparent inside. */
    private fun renderFrame(c: Canvas, w: Float, h: Float, r: Float, pal: WatchPalette, dark: Boolean) {
        val band = 10f
        val outer = Path().apply { addRoundRect(RectF(0f, 0f, w, h), r, r, Path.Direction.CW) }
        val inner = Path().apply { addRoundRect(RectF(band, band, w - band, h - band), r - band, r - band, Path.Direction.CW) }
        val ring = Path(outer).apply { op(inner, Path.Op.DIFFERENCE) }
        val p = Paint(Paint.ANTI_ALIAS_FLAG)
        // band body: lighter at the top, felt-tinted at the bottom
        val top = if (dark) a(0.80f, mix(pal.chassis4, WHITE, 0.10f)) else a(0.85f, WHITE)
        val bottom = if (dark) a(0.70f, mix(pal.glass, pal.felt, 0.45f)) else a(0.70f, pal.chassis3)
        p.shader = LinearGradient(0f, 0f, 0f, h, top, bottom, Shader.TileMode.CLAMP)
        c.drawPath(ring, p)
        // sheen on the upper band only
        c.save()
        c.clipPath(ring)
        p.shader = LinearGradient(0f, 0f, 0f, h * 0.45f, a(if (dark) 0.40f else 0.6f, WHITE), a(0f, WHITE), Shader.TileMode.CLAMP)
        c.drawRect(0f, 0f, w, h * 0.45f, p)
        c.restore()
        // lit outer rim: bright top-left, the table's accent at the bottom-right
        p.style = Paint.Style.STROKE
        p.strokeWidth = 2.75f
        val rim = LinearGradient(
            0f, 0f, 1f, 1f,
            intArrayOf(a(1f, if (dark) pal.glassRim else WHITE), a(0.35f, WHITE), a(0.15f, WHITE), a(0.9f, pal.accent)),
            floatArrayOf(0f, 0.35f, 0.6f, 1f), Shader.TileMode.CLAMP,
        )
        rim.setLocalMatrix(Matrix().apply { setScale(w, h) })
        p.shader = rim
        c.drawRoundRect(RectF(1.4f, 1.4f, w - 1.4f, h - 1.4f), r - 1.4f, r - 1.4f, p)
        // fine inner rim, the edge where the glass meets the clear middle
        p.strokeWidth = 1.25f
        p.shader = LinearGradient(0f, band, 0f, h - band, a(0.55f, WHITE), a(0.25f, pal.accent), Shader.TileMode.CLAMP)
        c.drawRoundRect(RectF(band, band, w - band, h - band), r - band, r - band, p)
        p.style = Paint.Style.FILL
        p.shader = null
    }
}

/** Draws cached glass with its element top-left at ([x], [y]). One drawImage. */
fun DrawScope.drawGlass(glass: GlassImage, x: Float, y: Float, alpha: Float = 1f) {
    if (alpha <= 0.002f) return
    drawImage(glass.image, Offset(x - glass.pad, y - glass.pad), alpha = alpha)
}

/** Draws cached glass of element size [w] x [h] centred at ([cx], [cy]), scaled by ([sx], [sy]). */
fun DrawScope.drawGlassScaled(glass: GlassImage, cx: Float, cy: Float, w: Float, h: Float, sx: Float, sy: Float, alpha: Float = 1f) {
    if (alpha <= 0.002f) return
    withTransform({ scale(sx, sy, Offset(cx, cy)) }) {
        drawImage(glass.image, Offset(cx - w / 2f - glass.pad, cy - h / 2f - glass.pad), alpha = alpha)
    }
}
