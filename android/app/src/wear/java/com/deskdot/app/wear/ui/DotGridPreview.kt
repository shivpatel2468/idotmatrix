package com.deskdot.app.wear.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.unit.Dp

private const val GRID = 32
private val UNLIT = Color(0xFF14_15_18)

/**
 * The shared 32x32 live preview (DESIGN_SPEC §5.7), used by Now Playing (pitch 6), Full view (pitch 9), In-game
 * (pitch 6) and the Tile. `frame` is the newest 3072-byte RGB row-major frame from the engine WebSocket (or
 * null before the first one arrives). Draws only on recomposition triggered by a new frame (the caller's
 * collectAsStateWithLifecycle on EngineClient.frame) — never on a timer, never in ambient.
 *
 * No allocation here: colours are computed per-cell on every draw call straight from the ByteArray, no
 * intermediate Bitmap/array is built (perf budget: "no allocations in draw code").
 */
@Composable
fun DotGridPreview(
    frame: ByteArray?,
    cellSize: Dp,
    modifier: Modifier = Modifier,
    ambient: Boolean = false,
) {
    val side = remember(cellSize) { cellSize * GRID.toFloat() }
    Canvas(modifier = modifier.size(side)) {
        val pitch = size.width / GRID
        val r = pitch * 0.375f // dot radius ~ pitch*2.25/6 scaled proportionally to the spec's pitch-6/r-2.25
        for (j in 0 until GRID) {
            for (i in 0 until GRID) {
                val idx = (j * GRID + i) * 3
                val lit: Boolean
                val color: Color
                if (frame != null && idx + 2 < frame.size) {
                    val rr = frame[idx].toInt() and 0xFF
                    val gg = frame[idx + 1].toInt() and 0xFF
                    val bb = frame[idx + 2].toInt() and 0xFF
                    lit = (rr + gg + bb) >= 24
                    color = if (lit) Color(rr, gg, bb) else UNLIT
                } else {
                    lit = false
                    color = UNLIT
                }
                if (ambient && !lit) continue // LE: unlit dots are simply not drawn
                drawDot(this, pitch, i, j, r, if (ambient) Color(0xFF8A8A8A) else color)
            }
        }
    }
}

private fun drawDot(scope: DrawScope, pitch: Float, i: Int, j: Int, r: Float, color: Color) {
    val cx = pitch * (i + 0.5f)
    val cy = pitch * (j + 0.5f)
    scope.drawCircle(color = color, radius = r, center = androidx.compose.ui.geometry.Offset(cx, cy))
}
