package com.deskdot.wear.design

import android.graphics.RectF
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.asComposePath
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.core.graphics.PathParser
import android.graphics.Path as APath
import androidx.compose.ui.graphics.Path as CPath

/**
 * Line icons in the Orbit launcher's style (a 24-unit grid, stroke 2, round caps and joins), one cached path each,
 * drawn with at most two drawPath calls. Plain shapes, no logos.
 */
class WIcon internal constructor(stroke: APath, fill: APath) {
    internal val strokePath: CPath = stroke.asComposePath()
    internal val fillPath: CPath? = if (fill.isEmpty) null else fill.asComposePath()
}

private class IconBuilder {
    val s = APath()
    val f = APath()
    fun p(d: String) = s.addPath(PathParser.createPathFromPathData(d))
    fun c(cx: Float, cy: Float, r: Float) = s.addCircle(cx, cy, r, APath.Direction.CW)
    fun cf(cx: Float, cy: Float, r: Float) = f.addCircle(cx, cy, r, APath.Direction.CW)
    fun r(x: Float, y: Float, w: Float, h: Float, rx: Float = 0f) = s.addRoundRect(RectF(x, y, x + w, y + h), rx, rx, APath.Direction.CW)
    fun build() = WIcon(s, f)
}

private fun icon(block: IconBuilder.() -> Unit): Lazy<WIcon> = lazy(LazyThreadSafetyMode.NONE) { IconBuilder().apply(block).build() }

object Icons {
    val add by icon { p("M12 5v14M5 12h14") }
    val remove by icon { p("M5 12h14") }
    val back by icon { p("M15 5l-7 7 7 7") }
    val next by icon { p("M9 5l7 7-7 7") }
    val retry by icon { p("M19.5 12a7.5 7.5 0 1 1-2.2-5.3"); p("M19.5 4v4h-4") }
    val sun by icon {
        c(12f, 12f, 4f)
        p("M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8")
    }
    val playlist by icon { p("M4 6h11M4 11h11M4 16h6"); p("M15 14.5v5.2l4.5-2.6z") }

    // One per kind of app (the studio's categories).
    val games by icon { r(2.5f, 7f, 19f, 11f, 5.5f); p("M7.5 10.5v4M5.5 12.5h4"); cf(15.5f, 11.3f, 1.2f); cf(17.8f, 13.7f, 1.2f) }
    val casino by icon { c(12f, 12f, 9f); c(12f, 12f, 4.5f); p("M12 3v3M12 18v3M3 12h3M18 12h3") }
    val pets by icon { cf(7f, 9f, 1.8f); cf(10.3f, 5.8f, 1.8f); cf(13.7f, 5.8f, 1.8f); cf(17f, 9f, 1.8f); p("M12 11.5c-3 0-5.5 3.6-5.5 6 0 1.8 1.6 2.5 3 2.5 1 0 1.6-.6 2.5-.6s1.5.6 2.5.6c1.4 0 3-.7 3-2.5 0-2.4-2.5-6-5.5-6z") }
    val time by icon { c(12f, 12f, 9f); p("M12 7v5l3.5 2") }
    val info by icon { p("M4 20V10M10 20V4M16 20v-7M21 20H3") }
    val media by icon { p("M9 18V5.5l11-2V16"); c(6.5f, 18f, 2.5f); c(17.5f, 16f, 2.5f) }
    val creative by icon { p("M4 20c3 0 4.5-1.4 4.5-3.6 0-1.4-1-2.4-2.3-2.4S4 15 4 16.5C4 18 3 19 2 19c.6.6 1.2 1 2 1z"); p("M8.3 14.2 19.5 3l1.5 1.5L9.8 15.7") }
    val ambient by icon { p("M12 21.5c-3.9 0-6.5-2.6-6.5-6.2 0-4.2 3.6-6.3 4.4-11 2.6 1.6 4 4.3 3.9 6.6 1-.6 1.8-1.8 2-3 1.9 1.8 2.7 4.4 2.7 6.6 0 4.1-2.6 7-6.5 7z") }
    val productivity by icon { r(4f, 3.5f, 16f, 17f, 2.5f); p("M8 9.5l2 2 4-4M8 16h8") }
    val other by icon { r(4f, 4f, 6f, 6f, 1.5f); r(14f, 4f, 6f, 6f, 1.5f); r(4f, 14f, 6f, 6f, 1.5f); r(14f, 14f, 6f, 6f, 1.5f) }

    fun forKind(kind: String): WIcon = when (kind) {
        "games" -> games
        "casino" -> casino
        "pets" -> pets
        "time" -> time
        "data" -> info
        "media" -> media
        "creative" -> creative
        "ambient" -> ambient
        "productivity" -> productivity
        else -> other
    }
}

private val IconStroke = Stroke(width = 2f, cap = StrokeCap.Round, join = StrokeJoin.Round)

/** Draws [icon] centred at ([cx], [cy]) at [size] px. Allocation-free. */
fun DrawScope.drawIcon(icon: WIcon, cx: Float, cy: Float, size: Float, color: Color, alpha: Float = 1f) {
    if (alpha <= 0.002f) return
    val k = size / 24f
    withTransform({
        translate(cx - size / 2f, cy - size / 2f)
        scale(k, k, Offset.Zero)
    }) {
        drawPath(icon.strokePath, color, alpha, style = IconStroke)
        icon.fillPath?.let { drawPath(it, color, alpha) }
    }
}
