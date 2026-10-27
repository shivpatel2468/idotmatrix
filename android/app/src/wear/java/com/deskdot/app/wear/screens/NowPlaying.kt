package com.deskdot.app.wear.screens

import android.graphics.Bitmap
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Shader
import android.os.SystemClock
import android.view.KeyEvent
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.PagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.navigation.NavHostController
import com.deskdot.app.wear.design.Ease
import com.deskdot.app.wear.design.Icons
import com.deskdot.app.wear.design.LocalHaptics
import com.deskdot.app.wear.design.LocalLook
import com.deskdot.app.wear.design.Neutral
import com.deskdot.app.wear.design.Semantic
import com.deskdot.app.wear.design.TAlign
import com.deskdot.app.wear.design.TS
import com.deskdot.app.wear.design.drawRun
import com.deskdot.app.wear.design.pxAt
import com.deskdot.app.wear.design.rememberPressLabel
import com.deskdot.app.wear.design.textRun
import com.deskdot.app.wear.nav.Route
import com.deskdot.app.wear.net.Readiness
import com.deskdot.app.wear.ui.FocusWhenActive
import com.deskdot.app.wear.ui.GlassButton
import com.deskdot.app.wear.ui.LabelMode
import com.deskdot.app.wear.ui.LocalDd
import com.deskdot.app.wear.ui.Screen
import com.deskdot.app.wear.ui.crownSteps
import com.deskdot.app.wear.ui.rememberDotRenderer
import com.deskdot.app.wear.ui.rememberLiveFrames
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

/** The 2 px glass rim (G5 gradient) around the preview, baked once (§5.3 "Preview frame (Wake)"). */
private fun bakeRim(): Bitmap {
    val bmp = Bitmap.createBitmap(200, 200, Bitmap.Config.ARGB_8888)
    val c = android.graphics.Canvas(bmp)
    fun a(al: Float) = ((al * 255).toInt() shl 24) or 0xFFFFFF
    val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 2f
        shader = LinearGradient(
            0f, 0f, 200f, 200f,
            intArrayOf(a(0.70f), a(0.22f), a(0.06f), a(0.12f), a(0.38f)),
            floatArrayOf(0f, 0.30f, 0.55f, 0.80f, 1f), Shader.TileMode.CLAMP,
        )
    }
    c.drawRoundRect(RectF(1f, 1f, 199f, 199f), 23f, 23f, p)
    return bmp
}

/**
 * §5.3 Now Playing (page 0), a fixed layout in px: the live 32x32 preview (pitch 6 at (112, 76) → 192 px),
 * Prev / Next glass circles at (60, 172) / (356, 172) with on-press labels, the preview itself as Play / Stop
 * (floating label pill at (208, 252)), the app name (baseline 306) and sub-line (baseline 338), the connection
 * dot at (208, 62). The crown sets panel brightness (±5 %, arc overlay); long-press opens the Full view.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun NowPlayingPage(nav: NavHostController, pager: PagerState) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val scope = rememberCoroutineScope()
    val active = pager.active(0)
    val state by dd.engine.state.collectAsState()
    val meta by dd.meta.collectAsState()
    val readiness by dd.engine.readiness.collectAsState()
    val fpsPref by dd.prefs.previewFps.collectAsState()
    var lastInput by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    var idle by remember { mutableStateOf(false) }

    LaunchedEffect(lastInput) {
        idle = false
        delay(30_000)
        idle = true
    }
    LaunchedEffect(Unit) { dd.loadMeta() }

    // §5.3 frame-rate caps: setting (10/5/2), ≤ 2 after 30 s idle, ≤ 4 in Calm, 1 in LE.
    val fps = when {
        look.le -> 1f
        else -> minOf(fpsPref.toFloat(), if (idle) 2f else 30f, if (look.calm) 4f else 30f)
    }
    val renderer = rememberDotRenderer(6, 2.25f)
    val tick = rememberLiveFrames(dd.engine, renderer, fps, look.le, active)
    val rim = remember { bakeRim().asImageBitmap() }

    // ---- crown = panel brightness, ±5 % per step, PATCH debounced (trailing 150 ms)
    var bright by remember { mutableIntStateOf(state?.brightness ?: 60) }
    var dragging by remember { mutableStateOf(false) }
    LaunchedEffect(state?.brightness) { if (!dragging) state?.brightness?.let { bright = it } }
    val arcAlpha = remember { Animatable(0f) }
    var patchJob by remember { mutableStateOf<Job?>(null) }
    var fadeJob by remember { mutableStateOf<Job?>(null) }
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus, active)

    fun stepBrightness(d: Int) {
        lastInput = SystemClock.elapsedRealtime()
        val next = (bright + 5 * d).coerceIn(5, 100)
        if (next == bright) {
            haptics.reject()
            return
        }
        haptics.tick()
        bright = next
        dragging = true
        fadeJob?.cancel()
        fadeJob = scope.launch {
            PagerChrome.dotsAlpha = 0f
            arcAlpha.snapTo(1f)
            delay(1200)
            arcAlpha.animateTo(0f, look.motion.tween(150, Ease.standardAccel))
            PagerChrome.dotsAlpha = 1f
        }
        patchJob?.cancel()
        patchJob = scope.launch {
            delay(150)
            dd.engine.patch("/api/settings", JSONObject().put("brightness", bright))
            dragging = false
        }
    }

    // I-13: pushers — top = next, bottom = previous (only if the system delivers them).
    val lifecycle = LocalLifecycleOwner.current
    LaunchedEffect(active, lifecycle) {
        if (!active) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            Signals.keys.collect { k ->
                lastInput = SystemClock.elapsedRealtime()
                haptics.confirm()
                dd.engine.post(if (k == KeyEvent.KEYCODE_STEM_1) "/api/playlist/next" else "/api/playlist/prev")
            }
        }
    }

    val s = state
    val connected = s?.device?.connected == true
    val connecting = s?.device?.connecting == true
    val dotColor = when {
        connected -> Semantic.ok
        connecting || readiness != Readiness.Ready && readiness != Readiness.Down -> Semantic.warn
        else -> Semantic.error
    }
    val dotPulse = remember { Animatable(1f) }
    val pulsing = dotColor == Semantic.warn && !look.le && !look.motion.cut
    LaunchedEffect(pulsing) {
        if (pulsing) dotPulse.animateTo(0.35f, infiniteRepeatable(tween(600, easing = LinearEasing), RepeatMode.Reverse)) else dotPulse.snapTo(1f)
    }

    val playing = s?.playing == true
    val appName = when {
        readiness == Readiness.Down && s == null -> "Engine off"
        s == null -> "Starting…"
        else -> meta?.name(s.currentApp)?.ifEmpty { null } ?: s.currentApp ?: "Nothing on"
    }
    val sub = when {
        s == null -> "DeskDot"
        !connected && s.device.address == null -> "No panel"
        !connected -> if (connecting) "Connecting…" else "Panel offline"
        playing && s.items.isNotEmpty() -> "${s.presetName ?: "Playlist"} · ${(s.plIndex % s.items.size) + 1} / ${s.items.size}"
        else -> "Pinned"
    }

    Box(Modifier.fillMaxSize().crownSteps(focus) { stepBrightness(it) }) {
        // Static chrome: frame rim, connection dot, name, sub-line, brightness arc (draw-only animation reads).
        Spacer(
            Modifier.fillMaxSize().drawWithCache {
                val nameRun = textRun(appName, TS.titleM(look.bold), 300f)
                val subRun = textRun(sub, TS.labelM(look.bold), 300f)
                onDrawBehind {
                    if (!look.le) drawImage(rim, Offset(108f, 72f))
                    drawCircle(dotColor, 4f, Offset(208f, 62f), alpha = dotPulse.value)
                    drawRun(nameRun, 208f, 306f, Neutral.onSurface, TAlign.InkCenter)
                    drawRun(subRun, 208f, 338f, look.variantText, TAlign.InkCenter)
                    val a = arcAlpha.value
                    if (a > 0f) {
                        val st = Stroke(6f, cap = StrokeCap.Round)
                        drawArc(Neutral.surface2, 60f, 60f, false, Offset(8f, 8f), Size(400f, 400f), alpha = a, style = st)
                        val frac = (bright - 5) / 95f
                        drawArc(look.roles.accent, 120f, -60f * frac, false, Offset(8f, 8f), Size(400f, 400f), alpha = a, style = st)
                    }
                }
            },
        )
        // The preview is the Play/Stop control; long-press opens the Full view.
        PreviewControl(
            playing = playing,
            onTap = {
                lastInput = SystemClock.elapsedRealtime()
                haptics.confirm()
                scope.launch { dd.engine.post(if (playing) "/api/playlist/stop" else "/api/playlist/play"); dd.engine.refreshState() }
            },
            onLong = {
                haptics.longPress()
                nav.navigate(Route.FULL)
            },
        ) {
            val t = tick.intValue
            if (renderer.hasFrame || t > 0) drawImage(renderer.image, Offset(4f, 4f))
        }
        GlassButton(Modifier.pxAt(60 - 48, 172 - 48, 96, 96), Icons.prev, "Previous", label = "Prev", labelMode = LabelMode.OnPress) {
            lastInput = SystemClock.elapsedRealtime()
            haptics.confirm()
            scope.launch { dd.engine.post("/api/playlist/prev") }
        }
        GlassButton(Modifier.pxAt(356 - 48, 172 - 48, 96, 96), Icons.next, "Next", label = "Next", labelMode = LabelMode.OnPress) {
            lastInput = SystemClock.elapsedRealtime()
            haptics.confirm()
            scope.launch { dd.engine.post("/api/playlist/next") }
        }
        // Tapping the app name opens the Apps page.
        Box(
            Modifier.pxAt(58, 276, 300, 40).semantics { contentDescription = "$appName, open Apps" }
                .pointerInput(Unit) { detectTapGestures { scope.launch { pager.animateScrollToPage(1) } } },
        )
    }
}

/** The 200x200 preview hit area at (108, 72) (the grid starts 4 px inside, at (112, 76)); the floating "Play"/"Stop" pill is its on-press label (§1.13). */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun PreviewControl(playing: Boolean, onTap: () -> Unit, onLong: () -> Unit, draw: androidx.compose.ui.graphics.drawscope.DrawScope.() -> Unit) {
    val look = LocalLook.current
    val src = remember { MutableInteractionSource() }
    val label = rememberPressLabel(src, look.motion)
    val text = if (playing) "Stop" else "Play"
    Box(
        Modifier.pxAt(108, 72, 200, 200)
            .semantics { contentDescription = "Panel preview. Tap to ${text.lowercase()} the playlist, hold for full view" }
            .combinedClickable(interactionSource = src, indication = null, onClick = onTap, onLongClick = onLong)
            .drawBehind(draw)
            .drawWithCache {
                val run = textRun(text, TS.labelCtl)
                val w = run.inkWidth + 24f
                onDrawWithContent {
                    drawContent()
                    val a = label.alpha
                    if (a > 0f) {
                        // centred at screen (208, 252) = local (100, 180); surface-3, 32 high, r 16, z 6.
                        drawRoundRect(Neutral.surface3, Offset(100f - w / 2f, 164f + label.lift), Size(w, 32f), CornerRadius(16f), alpha = a)
                        drawRun(run, 100f, 188.5f + label.lift, Neutral.onSurface, TAlign.InkCenter, a)
                    }
                }
            },
    )
}

/** §5.3 Full view: pitch 9 grid at origin (64, 64), opened over 250 ms emphasized-decel (LE: a cut). */
@Composable
fun FullViewScreen() {
    val dd = LocalDd.current
    val look = LocalLook.current
    val fpsPref by dd.prefs.previewFps.collectAsState()
    val renderer = rememberDotRenderer(9, 3.5f)
    val fps = if (look.le) 1f else minOf(fpsPref.toFloat(), if (look.calm) 4f else 30f)
    val tick = rememberLiveFrames(dd.engine, renderer, fps, look.le)
    val open = remember { Animatable(if (look.motion.cut) 1f else 0f) }
    LaunchedEffect(Unit) { open.animateTo(1f, look.motion.tween(250, Ease.emphasizedDecel)) }
    Screen {
        Spacer(
            Modifier.fillMaxSize()
                .graphicsLayer {
                    val p = open.value
                    alpha = p
                    scaleX = 0.67f + 0.33f * p
                    scaleY = 0.67f + 0.33f * p
                }
                .semantics { contentDescription = "Panel, full view" }
                .drawBehind {
                    tick.intValue
                    if (renderer.hasFrame) drawImage(renderer.image, Offset(64f, 64f))
                },
        )
    }
}
