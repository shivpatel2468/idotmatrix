package com.deskdot.app.wear.ui

import android.graphics.Bitmap
import android.os.SystemClock
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.IntState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.deskdot.app.wear.net.EngineClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.math.sqrt

/**
 * §5.7 live panel preview: 32x32 dots rendered into ONE reused ARGB bitmap of exactly `32 * pitch` px
 * (pitch 6 → 192 px = 96 dp, which is the spec's 192 px on this 2 px/dp screen; the earlier build sized it in dp
 * and drew it twice as large). Each frame is one pass over a reused IntArray with a pre-computed anti-aliased dot
 * mask, then one `setPixels` and one `drawImage`. No per-frame allocation.
 *
 * Unlit dots (RGB sum < 24) are `#141518` in Wake and not drawn in Low Energy (§5.3).
 */
@Stable
class DotRenderer(val pitch: Int, private val radius: Float) {
    val side = 32 * pitch
    private val pixels = IntArray(side * side)
    private val bitmap: Bitmap = Bitmap.createBitmap(side, side, Bitmap.Config.ARGB_8888)
    val image: ImageBitmap = bitmap.asImageBitmap()
    private val local = ByteArray(EngineClient.FRAME_BYTES)

    /** Coverage of each pixel of one pitch x pitch cell (0..255), anti-aliased. */
    private val mask = IntArray(pitch * pitch).also { m ->
        val c = pitch / 2f
        for (y in 0 until pitch) for (x in 0 until pitch) {
            // 4x4 supersampling
            var hit = 0
            for (sy in 0 until 4) for (sx in 0 until 4) {
                val dx = x + (sx + 0.5f) / 4f - c
                val dy = y + (sy + 0.5f) / 4f - c
                if (sqrt(dx * dx + dy * dy) <= radius) hit++
            }
            m[y * pitch + x] = hit * 255 / 16
        }
    }

    var hasFrame = false
        private set

    /** Copies the client's newest frame and rasterises it. Safe on any thread (only this renderer writes). */
    fun render(src: ByteArray, lowEnergy: Boolean, grey: Boolean = false) {
        synchronized(src) { System.arraycopy(src, 0, local, 0, local.size) }
        val p = pitch
        val unlit = if (lowEnergy) 0 else 0x141518
        var i = 0
        for (cy in 0 until 32) {
            for (cx in 0 until 32) {
                var r = local[i].toInt() and 0xFF
                var g = local[i + 1].toInt() and 0xFF
                var b = local[i + 2].toInt() and 0xFF
                i += 3
                val lit = r + g + b >= 24
                if (!lit) {
                    r = (unlit shr 16) and 0xFF; g = (unlit shr 8) and 0xFF; b = unlit and 0xFF
                } else if (grey) {
                    r = 0x8A; g = 0x90; b = 0x99
                }
                val draw = lit || !lowEnergy
                val base = (cy * p) * side + cx * p
                for (y in 0 until p) {
                    val row = base + y * side
                    val mrow = y * p
                    for (x in 0 until p) {
                        val a = if (draw) mask[mrow + x] else 0
                        // premultiplied-free ARGB: alpha carries the dot's anti-aliasing over black
                        pixels[row + x] = (a shl 24) or (r shl 16) or (g shl 8) or b
                    }
                }
            }
        }
        hasFrame = true
    }

    /** Main thread: push the pixels into the bitmap (HWUI re-uploads it on the next draw). */
    fun commit() {
        bitmap.setPixels(pixels, 0, side, 0, 0, side, side)
    }
}

/**
 * Drives a [DotRenderer] from the engine's frames **only while the screen is RESUMED** (never in the
 * background or with the screen off): it acquires the WebSocket, renders at most [fps] frames per second
 * (dropping intermediate frames: latest wins), and falls back to `GET /api/frame` every 500 ms while the
 * socket is down. Returns a draw counter: read `.intValue` ONLY inside a draw lambda (draw-only invalidation,
 * no recomposition per frame).
 */
@Composable
fun rememberLiveFrames(engine: EngineClient, renderer: DotRenderer, fps: Float, lowEnergy: Boolean, active: Boolean = true): IntState {
    val tick = remember { mutableIntStateOf(0) }
    val lifecycle = LocalLifecycleOwner.current
    val curFps by rememberUpdatedState(fps)
    val le by rememberUpdatedState(lowEnergy)
    LaunchedEffect(lifecycle, renderer, active) {
        if (!active) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            engine.acquireSocket()
            try {
                var lastSeq = -1
                while (true) {
                    val up = engine.socketUp.value
                    // WebSocket down: poll the REST frame (the loop below waits ≥ 500 ms) until it comes back.
                    if (!up) engine.pollFrame(1_500)
                    val seq = if (up) withTimeoutOrNull(2_000) { engine.frameSeq.first { it != lastSeq } } ?: engine.frameSeq.value else engine.frameSeq.value
                    if (seq != lastSeq) {
                        lastSeq = seq
                        withContext(Dispatchers.Default) { renderer.render(engine.frame, le) }
                        renderer.commit()
                        tick.intValue++
                    }
                    delay((1000f / curFps.coerceIn(0.5f, 30f)).toLong().coerceAtLeast(if (up) 33L else 500L))
                }
            } finally {
                engine.releaseSocket()
            }
        }
    }
    return tick
}

/** A renderer that lives as long as the composable (one bitmap per size, §5.7). */
@Composable
fun rememberDotRenderer(pitch: Int, radius: Float): DotRenderer = remember(pitch, radius) { DotRenderer(pitch, radius) }

/** Releases nothing (bitmaps are GC'd with the renderer) but documents the lifetime for readers. */
@Composable
fun DotRendererLifetime(r: DotRenderer) = DisposableEffect(r) { onDispose { } }
