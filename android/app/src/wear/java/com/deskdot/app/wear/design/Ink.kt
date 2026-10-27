package com.deskdot.app.wear.design

import android.content.Context
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.Typeface
import android.text.TextPaint
import android.text.TextUtils
import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.core.content.res.ResourcesCompat
import com.deskdot.app.R

/**
 * §1.6 typography, drawn the way the approved preview draws it: every run is positioned by its
 * **baseline** and, where the preview centres text, by its **ink** box (rule N2), not by a
 * Compose text box. Runs are measured once (inside `drawWithCache`) and drawn with a single
 * `Canvas.drawText` call, so scrolling never re-lays-out text.
 *
 * Static instances (§1.6.2) are bundled under res/font. gsf_800r is used only for the
 * alphabet-scrub centre letter (§4.4.1).
 */
enum class OFont(val res: Int) {
    G450(R.font.gsf_450),
    G600(R.font.gsf_600),
    G700(R.font.gsf_700),
    G600R(R.font.gsf_600r),
    G800R(R.font.gsf_800r),
    M500(R.font.jbm_500),
    M700(R.font.jbm_700),
    ;

    /** §1.6.1 / §4.1: Low Energy (and sun boost) add +100 weight, capped at 700. 550 -> 600. */
    fun bumped(on: Boolean): OFont = if (!on) this else when (this) {
        G450 -> G600
        G600 -> G700
        else -> this
    }
}

object SuiteFonts {
    private val faces = arrayOfNulls<Typeface>(OFont.entries.size)

    @Volatile
    private var appContext: Context? = null

    fun init(context: Context) {
        appContext = context.applicationContext
    }

    /** Called once from a background thread at process start so the first frame never parses fonts. */
    fun preload() {
        OFont.entries.forEach { typeface(it) }
    }

    fun typeface(f: OFont): Typeface {
        faces[f.ordinal]?.let { return it }
        synchronized(this) {
            faces[f.ordinal]?.let { return it }
            val ctx = appContext
            val t = if (ctx != null) runCatching { ResourcesCompat.getFont(ctx, f.res) }.getOrNull() else null
            val face = t ?: Typeface.DEFAULT
            faces[f.ordinal] = face
            return face
        }
    }
}

/** A text style in device px (1 sp = 2 px at font scale 1.0). */
@Immutable
data class TStyle(
    val font: OFont,
    val sizePx: Float,
    val letterSpacingPx: Float = 0f,
    val tnum: Boolean = false,
    /** label-ctl is clamped at font scale 1.0 (§6). */
    val scalable: Boolean = true,
)

/** Main-thread text resources. Paints are shared; colour is set per draw (recording canvases copy paints). */
object Ink {
    /** System font scale, clamped at 1.24 (§6). Set by the activity on configuration. */
    var fontScale: Float = 1f
        set(value) {
            val v = value.coerceIn(0.85f, 1.24f)
            if (v != field) {
                field = v
                paints.clear()
            }
        }

    private val paints = HashMap<TStyle, TextPaint>()

    fun paint(s: TStyle): TextPaint = paints.getOrPut(s) {
        TextPaint(Paint.ANTI_ALIAS_FLAG or Paint.SUBPIXEL_TEXT_FLAG).apply {
            typeface = SuiteFonts.typeface(s.font)
            val size = if (s.scalable) s.sizePx * fontScale else s.sizePx
            textSize = size
            if (s.letterSpacingPx != 0f) letterSpacing = s.letterSpacingPx / size
            if (s.tnum) fontFeatureSettings = "'tnum'"
        }
    }
}

/** Common styles, in px, exactly as the preview draws them (preview.html row builders). */
object TS {
    fun titleL(b: Boolean = false) = TStyle(OFont.G600.bumped(b), 40f)
    fun titleM(b: Boolean = false) = TStyle(OFont.G600.bumped(b), 32f)
    fun labelL(b: Boolean = false) = TStyle(OFont.G600.bumped(b), 28f, 0.28f)
    fun labelM(b: Boolean = false) = TStyle(OFont.G600.bumped(b), 24f, 0.5f)
    fun body26(b: Boolean = false) = TStyle(OFont.G450.bumped(b), 26f)
    fun bodyL(b: Boolean = false) = TStyle(OFont.G450.bumped(b), 30f)
    fun mono(sizePx: Float = 24f) = TStyle(OFont.M500, sizePx, tnum = true)

    /** §1.6.4 label-ctl: gsf_700, 12 sp (24 px), +0.03 em (+0.7 px). Clamped at font scale 1.0. */
    val labelCtl = TStyle(OFont.G700, 24f, 0.7f, scalable = false)
}

enum class TAlign { Start, InkCenter, InkEnd, AdvanceCenter }

/** A measured, possibly ellipsised, run. Build inside drawWithCache / remember, never per frame. */
class TextRun(text: String, val paint: TextPaint, maxWidthPx: Float = Float.MAX_VALUE) {
    val text: String = if (maxWidthPx < Float.MAX_VALUE && paint.measureText(text) > maxWidthPx) {
        // measured ellipsis (same result on every platform, including the JVM screenshot tests)
        var k = text.length
        while (k > 1 && paint.measureText(text.substring(0, k).trimEnd() + "…") > maxWidthPx) k--
        text.substring(0, k).trimEnd() + "…"
    } else {
        text
    }
    val inkLeft: Float
    val inkRight: Float
    val inkTop: Float
    val inkBottom: Float
    val advance: Float = paint.measureText(this.text)

    init {
        val r = Rect()
        paint.getTextBounds(this.text, 0, this.text.length, r)
        inkLeft = r.left.toFloat()
        inkRight = r.right.toFloat()
        inkTop = r.top.toFloat()
        inkBottom = r.bottom.toFloat()
    }

    val inkWidth: Float get() = inkRight - inkLeft
    val inkCentreX: Float get() = (inkLeft + inkRight) / 2f

    /** x of the run origin for the given alignment anchor. */
    fun originX(x: Float, align: TAlign): Float = when (align) {
        TAlign.Start -> x
        TAlign.InkCenter -> x - inkCentreX
        TAlign.InkEnd -> x - inkRight
        TAlign.AdvanceCenter -> x - advance / 2f
    }
}

fun textRun(text: String, style: TStyle, maxWidthPx: Float = Float.MAX_VALUE) =
    TextRun(text, Ink.paint(style), maxWidthPx)

/** Draw [run] with its baseline at [baseline]. [alpha] multiplies the colour's alpha. */
fun DrawScope.drawRun(
    run: TextRun,
    x: Float,
    baseline: Float,
    color: Color,
    align: TAlign = TAlign.Start,
    alpha: Float = 1f,
) {
    if (alpha <= 0.002f) return
    val p = run.paint
    p.color = if (alpha >= 1f) color.toArgb() else color.copy(alpha = color.alpha * alpha).toArgb()
    drawContext.canvas.nativeCanvas.drawText(run.text, run.originX(x, align), baseline, p)
}
