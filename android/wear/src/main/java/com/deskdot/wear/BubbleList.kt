package com.deskdot.wear

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.foundation.focusable
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.rotary.onRotaryScrollEvent
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.deskdot.wear.theme.WatchPalette
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlin.math.abs

/** Distance (px) of item [index]'s centre from the viewport's centre, or null if it isn't laid out. */
/** Item [it]'s centre on the actual screen, minus the screen's centre (px). Works with uneven content padding. */
private fun LazyListState.fromScreenCentre(it: androidx.compose.foundation.lazy.LazyListItemInfo): Float {
    val li = layoutInfo
    val onScreen = it.offset - li.viewportStartOffset + it.size / 2f
    return onScreen - li.viewportSize.height / 2f
}

private fun LazyListState.offsetOf(index: Int): Float? =
    layoutInfo.visibleItemsInfo.firstOrNull { it.index == index }?.let { fromScreenCentre(it) }

private fun LazyListState.centre(): Pair<Int, Float>? =
    layoutInfo.visibleItemsInfo.minByOrNull { abs(fromScreenCentre(it)) }?.let { it.index to fromScreenCentre(it) }

/**
 * Orbit's bubbly glass list, for DeskDot: rows on OLED black that curve away at the round edge, snap to the
 * centre, and a glass bubble that floats ABOVE the centred row and moves with the scroll — it clings to the
 * row as it slides away (trailing like liquid), pops across to the next row with a wobble, and springs back
 * when the list settles. The crown scrolls it too. Rows whose index is in [noBubble] (a header, the preview)
 * hide the bubble while centred. The frame loop runs only while the list moves.
 */
@Composable
fun BubbleList(
    count: Int,
    palette: WatchPalette,
    focus: FocusRequester,
    rowHeight: Dp = 52.dp,
    /** Height of the first item when it's taller than a row (a preview card), so it can sit centred too. */
    firstHeight: Dp = rowHeight,
    noBubble: Set<Int> = emptySet(),
    still: Boolean = false,
    row: @Composable (index: Int) -> Unit,
) {
    val state = rememberLazyListState()
    val scope = rememberCoroutineScope()
    var shift by remember { mutableFloatStateOf(0f) }
    var lag by remember { mutableFloatStateOf(0f) }
    var centred by remember { mutableFloatStateOf(0f) } // index of the centred row, as a float state
    val pop = remember { Animatable(0f) }
    val settle = remember { spring<Float>(dampingRatio = 0.38f, stiffness = 300f) }
    val wobble = remember { spring<Float>(dampingRatio = 0.28f, stiffness = 420f) }

    // True while our own snap runs, so its end never triggers another snap (that looped forever).
    val snapping = remember { booleanArrayOf(false) }
    LaunchedEffect(state, still) {
        snapshotFlow { state.isScrollInProgress }.collectLatest { scrolling ->
            coroutineScope {
                if (!scrolling) {
                    // Snap the nearest row to the centre once (by its exact distance, so rows of any
                    // height land centred), then let the bubble spring home under it.
                    val c = state.centre()
                    if (!snapping[0] && c != null && abs(c.second) > 2f) {
                        snapping[0] = true
                        state.animateScrollBy(c.second)
                        return@coroutineScope
                    }
                    snapping[0] = false
                    if (!still) {
                        Animatable(shift).animateTo(0f, settle) {
                            shift = value
                            lag = -value * 0.35f
                        }
                    }
                    shift = 0f
                    lag = 0f
                    return@coroutineScope
                }
                var last = state.centre()?.first ?: -1
                while (true) {
                    withFrameNanos { }
                    val c = state.centre() ?: continue
                    centred = c.first.toFloat()
                    if (still) continue
                    val target = c.second * 0.6f
                    shift += (target - shift) * 0.38f
                    lag = target - shift
                    if (c.first != last) {
                        last = c.first
                        launch {
                            pop.snapTo(1f)
                            pop.animateTo(0f, wobble)
                        }
                    }
                }
            }
        }
    }
    LaunchedEffect(state) { snapshotFlow { state.centre()?.first ?: 0 }.collect { centred = it.toFloat() } }

    Box(Modifier.fillMaxSize()) {
        LazyColumn(
            state = state,
            contentPadding = PaddingValues(top = (208.dp - firstHeight) / 2, bottom = (208.dp - rowHeight) / 2),
            modifier = Modifier
                .fillMaxSize()
                .onRotaryScrollEvent { e ->
                    scope.launch { state.scrollBy(e.verticalScrollPixels) }
                    true
                }
                .focusRequester(focus)
                .focusable(),
        ) {
            items(count) { i ->
                Box(
                    Modifier
                        .fillMaxWidth()
                        .graphicsLayer {
                            // A gentle curve at the round edge: rows shrink and fade away from the centre.
                            val d = state.offsetOf(i) ?: 0f
                            val t = (abs(d) / 208f).coerceIn(0f, 1f)
                            val s = 1f - 0.16f * t * t
                            scaleX = s
                            scaleY = s
                            alpha = 1f - 0.55f * t * t
                        },
                ) { row(i) }
            }
        }
        // The bubble, above the rows.
        Spacer(
            Modifier.fillMaxSize().drawBehind {
                if (centred.toInt() in noBubble) return@drawBehind
                val p = pop.value
                val w0 = size.width * 0.86f
                val h0 = rowHeight.toPx()
                val h = h0 * (1f - 0.07f * p) + abs(lag) * 0.9f
                val w = w0 * (1f + 0.05f * p) - abs(lag) * 0.25f
                // Anchored to where the centred row really is (read every frame), plus the liquid trail.
                val rowAt = state.centre()?.second ?: 0f
                val cy = size.height / 2f + rowAt + lag * 0.5f
                val tl = Offset((size.width - w) / 2f, cy - h / 2f)
                val r = CornerRadius(h / 2f)
                val accent = Color(palette.accent)
                drawRoundRect(accent.copy(alpha = 0.14f), tl, Size(w, h), r, style = Stroke(10f))
                drawRoundRect(Color.White.copy(alpha = 0.035f), tl, Size(w, h), r)
                drawRoundRect(
                    Brush.verticalGradient(
                        0f to Color.White.copy(alpha = 0.75f), 0.45f to accent.copy(alpha = 0.55f), 1f to Color.White.copy(alpha = 0.25f),
                        startY = tl.y, endY = tl.y + h,
                    ),
                    tl, Size(w, h), r, style = Stroke(2.5f),
                )
                // Inner highlight along the top edge: the glass catching light.
                drawRoundRect(Color.White.copy(alpha = 0.18f), Offset(tl.x + h * 0.35f, tl.y + 3f), Size(w - h * 0.7f, 3f), CornerRadius(2f))
            },
        )
    }
}
