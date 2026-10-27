package com.deskdot.app.wear.design

import android.graphics.RectF
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
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
 * §1.11 icons, ported 1:1 from the approved preview's icon set (preview.html `IC`, a 24-unit grid,
 * stroke 2, round caps and joins — the preview's own approximations of Material Symbols Rounded).
 * Each icon is one cached stroke path (+ an optional fill path), built once and drawn with at most
 * three drawPath calls; no vector-drawable inflation or per-frame allocation.
 */
class OIcon internal constructor(stroke: APath, fill: APath, dashed: APath?) {
    internal val strokePath: CPath = stroke.asComposePath()
    internal val fillPath: CPath? = if (fill.isEmpty) null else fill.asComposePath()
    internal val dashedPath: CPath? = dashed?.asComposePath()
}

private class IconBuilder {
    val s = APath()
    val f = APath()
    var dashed: APath? = null

    fun p(d: String) = s.addPath(PathParser.createPathFromPathData(d))
    fun c(cx: Float, cy: Float, r: Float) = s.addCircle(cx, cy, r, APath.Direction.CW)
    fun cf(cx: Float, cy: Float, r: Float) = f.addCircle(cx, cy, r, APath.Direction.CW)
    fun r(x: Float, y: Float, w: Float, h: Float, rx: Float = 0f) =
        s.addRoundRect(RectF(x, y, x + w, y + h), rx, rx, APath.Direction.CW)

    fun rf(x: Float, y: Float, w: Float, h: Float) = f.addRect(RectF(x, y, x + w, y + h), APath.Direction.CW)
    fun fr(x: Float, y: Float, w: Float, h: Float) = f.addRoundRect(RectF(x, y, x + w, y + h), 1.5f, 1.5f, APath.Direction.CW)
    fun fp(d: String) = f.addPath(PathParser.createPathFromPathData(d))
    fun e(cx: Float, cy: Float, rx: Float, ry: Float) =
        s.addOval(RectF(cx - rx, cy - ry, cx + rx, cy + ry), APath.Direction.CW)

    fun dashedCircle(cx: Float, cy: Float, r: Float) {
        dashed = APath().apply { addCircle(cx, cy, r, APath.Direction.CW) }
    }

    fun build() = OIcon(s, f, dashed)
}

private fun icon(block: IconBuilder.() -> Unit): Lazy<OIcon> =
    lazy(LazyThreadSafetyMode.NONE) { IconBuilder().apply(block).build() }

object Icons {
    // ---- DeskDot Watch (§1.11 / preview.html IC) ----
    val prev by icon { p("M7 6v12"); fp("M18 6v12l-9-6z") }
    val next by icon { p("M17 6v12"); fp("M6 6v12l9-6z") }
    val play by icon { fp("M8 5v14l11-7z") }
    val stop by icon { fr(6.5f, 6.5f, 11f, 11f) }
    val link by icon { p("M10 14a4 4 0 0 0 5.6 0l3-3a4 4 0 0 0-5.6-5.6l-1 1M14 10a4 4 0 0 0-5.6 0l-3 3a4 4 0 0 0 5.6 5.6l1-1") }
    val linkOff by icon { p("M10 14a4 4 0 0 0 5.6 0l3-3a4 4 0 0 0-5.6-5.6l-1 1M14 10a4 4 0 0 0-5.6 0l-3 3a4 4 0 0 0 5.6 5.6l1-1M3 3l18 18") }
    val sync by icon { p("M20 12a8 8 0 0 1-14 5.3M4 12a8 8 0 0 1 14-5.3M18 3v4h-4M6 21v-4h4") }
    val btScan by icon { p("M5 7l10 10-5 5V2l5 5L5 17"); p("M18.5 9.5a4 4 0 0 1 0 5M21 7a8 8 0 0 1 0 10") }
    val group by icon { c(9f, 8f, 3.5f); p("M2.5 19a6.5 6.5 0 0 1 13 0"); c(17f, 9f, 2.5f); p("M16 14a5 5 0 0 1 6 5") }
    val fan by icon { c(12f, 12f, 2f); p("M12 10c-1-5 2-8 5-6s0 6-5 6zM14 12c5-1 8 2 6 5s-6 0-6-5zM12 14c1 5-2 8-5 6s0-6 5-6zM10 12c-5 1-8-2-6-5s6 0 6 5z") }
    val qr by icon { r(3f, 3f, 7f, 7f); r(14f, 3f, 7f, 7f); r(3f, 14f, 7f, 7f); p("M14 14h3v3h-3zM18 18h3v3h-3zM14 20h1M20 14h1") }
    val games by icon { p("M6 8h12a4 4 0 0 1 4 4l-1 5a2.5 2.5 0 0 1-4.3 1.2L15 16H9l-1.7 2.2A2.5 2.5 0 0 1 3 17l-1-5a4 4 0 0 1 4-4z"); p("M8 11v3M6.5 12.5h3"); cf(16f, 12.5f, 1f) }
    val chat by icon { p("M4 5h16v11H9l-5 4z") }
    val tv by icon { r(3f, 6f, 18f, 12f, 2f); p("M8 21h8M8 2l4 4 4-4") }
    val restart by icon { p("M5 12a7 7 0 1 0 2.2-5.1"); p("M5 4v4h4") }
    val power by icon { p("M12 3v8"); p("M7 6.5a7 7 0 1 0 10 0") }
    val openNew by icon { p("M14 4h6v6M20 4l-9 9"); p("M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5") }
    val shuffle by icon { p("M3 7h4l10 10h4M3 17h4l3-3M14 10l3-3h4M18 4l3 3-3 3M18 14l3 3-3 3") }
    val playlistAdd by icon { p("M3 6h12M3 11h12M3 16h7M17 13v8M13 17h8") }
    val star by icon { p("M12 3l2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 16.8l-5.4 2.9 1.1-6.1L3.2 9.4l6.1-.8z") }
    val display by icon { r(3f, 4f, 18f, 13f, 2f); p("M9 21h6M12 17v4") }
    val cpu by icon { r(6f, 6f, 12f, 12f, 2f); r(9.5f, 9.5f, 5f, 5f); p("M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3") }
    val chevronUp by icon { p("M5 15l7-7 7 7") }
    val chevronLeft by icon { p("M15 5l-7 7 7 7") }
    val moon by icon { p("M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z") }
    val rotate by icon { p("M5 12a7 7 0 1 0 2.2-5.1"); p("M5 4v4h4"); cf(12f, 12f, 1.6f) }
    val swap by icon { p("M4 8h14l-3-3M20 16H6l3 3") }
    val speed by icon { p("M4 17a8 8 0 1 1 16 0"); p("M12 17l4-5") }
    val handoff by icon { p("M4 12h11M11 8l4 4-4 4"); p("M17 4h3v16h-3") }
    val units by icon { p("M4 18h16M6 18v-3M10 18v-5M14 18v-3M18 18v-5") }
    val place by icon { p("M12 21s-6-5.4-6-11a6 6 0 0 1 12 0c0 5.6-6 11-6 11z"); c(12f, 10f, 2.2f) }
    val address by icon { p("M4 12h16M12 4a12 12 0 0 1 0 16M12 4a12 12 0 0 0 0 16"); c(12f, 12f, 8f) }
    val hourglass by icon { p("M7 3h10M7 21h10M8 3c0 5 8 5 8 9s-8 4-8 9M16 3c0 5-8 5-8 9s8 4 8 9") }
    val keyboard by icon { r(3f, 6f, 18f, 12f, 2f); p("M7 10h.01M11 10h.01M15 10h.01M8 14h8") }

    val search by icon { c(10f, 10f, 6f); p("M14.5 14.5 20 20") }
    val wifi by icon {
        p("M2.5 9a14 14 0 0 1 19 0M5.5 12.5a9.5 9.5 0 0 1 13 0M8.8 16a5 5 0 0 1 6.4 0"); cf(12f, 19.3f, 1.3f)
    }
    val wifiOff by icon {
        p("M2.5 9a14 14 0 0 1 19 0M5.5 12.5a9.5 9.5 0 0 1 13 0M8.8 16a5 5 0 0 1 6.4 0"); cf(12f, 19.3f, 1.3f)
        p("M3 3l18 18")
    }
    val bluetooth by icon { p("M7 7l10 10-5 5V2l5 5L7 17") }
    val dnd by icon { c(12f, 12f, 9f); p("M7.5 12h9") }
    val theater by icon { p("M3 4h10v6a5 5 0 0 1-10 0z"); p("M11 13.5h10v3a5 5 0 0 1-10 0z") }
    val batterySaver by icon { r(7f, 4f, 10f, 17f, 2f); p("M10 2h4M12 9v6M9 12h6") }
    val eco by icon { p("M5 19C5 10 11 5 20 4c-1 9-6 15-15 15zM5 19l8-8") }
    val sun by icon {
        c(12f, 12f, 4f)
        p("M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8")
    }
    val pin by icon { p("M9 3h6l-1 6 3 4H7l3-4zM12 13v8") }
    val keepOff by icon { p("M9 3h6l-1 6 3 4H7l3-4zM12 13v8"); p("M3 3l18 18") }
    val info by icon { c(12f, 12f, 9f); p("M12 11v6"); cf(12f, 7.6f, 1.2f) }
    val visibilityOff by icon {
        p("M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"); c(12f, 12f, 3f); p("M3 3l18 18")
    }
    val gear by icon { c(12f, 12f, 3f); dashedCircle(12f, 12f, 7.5f) }
    val history by icon { p("M4.5 13a7.5 7.5 0 1 0 2-6.2"); p("M4 4v4h4M12 8v4l3 2") }
    val check by icon { p("M5 12.5l4.5 4.5L19 7.5") }
    val close by icon { p("M6 6l12 12M18 6 6 18") }
    val arrowOutward by icon { p("M8 16 16 8M9 8h7v7") }
    val memory by icon {
        r(5f, 5f, 14f, 14f, 2f); p("M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3")
    }
    val storage by icon { r(5f, 3f, 14f, 18f, 2f); p("M9 7h6") }
    val grid by icon { r(4f, 4f, 6f, 6f); r(14f, 4f, 6f, 6f); r(4f, 14f, 6f, 6f); r(14f, 14f, 6f, 6f) }
    val viewList by icon { r(4f, 4f, 16f, 6f, 1.5f); r(4f, 14f, 16f, 6f, 1.5f) }
    val compact by icon { p("M4 5h16M4 9.7h16M4 14.3h16M4 19h16") }
    val palette by icon { c(12f, 12f, 9f); cf(8f, 10f, 1.4f); cf(12f, 7f, 1.4f); cf(16f, 10f, 1.4f) }
    val shape by icon {
        p("M12 3l2.5 3.2 4-.6-.6 4L21 12l-3.1 2.4.6 4-4-.6L12 21l-2.5-3.2-4 .6.6-4L3 12l3.1-2.4-.6-4 4 .6z")
    }
    val vibration by icon { r(8f, 4f, 8f, 16f, 2f); p("M4 8v8M20 8v8") }
    val chevronRight by icon { p("M9 5l7 7-7 7") }
    val thermostat by icon { p("M10 13.5V5a2 2 0 0 1 4 0v8.5a4 4 0 1 1-4 0z"); cf(12f, 16.6f, 1.9f) }
    val arrowUp by icon { p("M6 15l6-6 6 6") }
    val arrowDown by icon { p("M6 9l6 6 6-6") }
    val add by icon { p("M12 5v14M5 12h14") }
    val remove by icon { p("M5 12h14") }
}

private val IconStroke = Stroke(width = 2f, cap = StrokeCap.Round, join = StrokeJoin.Round)
private val GearStroke = Stroke(
    width = 3.6f,
    pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.2f, 2.7f), 0f),
)

/** Draws [icon] centred at ([cx], [cy]) at [size] px. Allocation-free. */
fun DrawScope.drawIcon(icon: OIcon, cx: Float, cy: Float, size: Float, color: Color, alpha: Float = 1f) {
    if (alpha <= 0.002f) return
    val k = size / 24f
    withTransform({
        translate(cx - size / 2f, cy - size / 2f)
        scale(k, k, Offset.Zero)
    }) {
        drawPath(icon.strokePath, color, alpha, style = IconStroke)
        icon.fillPath?.let { drawPath(it, color, alpha) }
        icon.dashedPath?.let { drawPath(it, color, alpha, style = GearStroke) }
    }
}
