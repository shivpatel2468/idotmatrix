package com.deskdot.app.wear.screens

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.os.Process
import android.os.SystemClock
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.navigation.NavHostController
import com.deskdot.app.EngineService
import com.deskdot.app.wear.Dd
import com.deskdot.app.wear.design.Ease
import com.deskdot.app.wear.design.HeaderItem
import com.deskdot.app.wear.design.Icons
import com.deskdot.app.wear.design.LocalHaptics
import com.deskdot.app.wear.design.LocalLook
import com.deskdot.app.wear.design.Neutral
import com.deskdot.app.wear.design.OFont
import com.deskdot.app.wear.design.Semantic
import com.deskdot.app.wear.design.SettingItem
import com.deskdot.app.wear.design.SuiteList
import com.deskdot.app.wear.design.TAlign
import com.deskdot.app.wear.design.TS
import com.deskdot.app.wear.design.TStyle
import com.deskdot.app.wear.design.Trailing
import com.deskdot.app.wear.design.drawRun
import com.deskdot.app.wear.design.pxAt
import com.deskdot.app.wear.design.rememberPressLabel
import com.deskdot.app.wear.design.rememberSuiteListState
import com.deskdot.app.wear.design.textRun
import com.deskdot.app.wear.host.WifiLease
import com.deskdot.app.wear.nav.ChoiceReq
import com.deskdot.app.wear.nav.NumberReq
import com.deskdot.app.wear.nav.Pick
import com.deskdot.app.wear.nav.Route
import com.deskdot.app.wear.nav.rescan
import com.deskdot.app.wear.net.HostInfo
import com.deskdot.app.wear.net.Readiness
import com.deskdot.app.wear.sys.DeviceStats
import com.deskdot.app.wear.ui.Act
import com.deskdot.app.wear.ui.ActionRowItem
import com.deskdot.app.wear.ui.Btn
import com.deskdot.app.wear.ui.DataRowItem
import com.deskdot.app.wear.ui.FocusWhenActive
import com.deskdot.app.wear.ui.GlassButton
import com.deskdot.app.wear.ui.GlassPillItem
import com.deskdot.app.wear.ui.HeroItem
import com.deskdot.app.wear.ui.LabelMode
import com.deskdot.app.wear.ui.LocalDd
import com.deskdot.app.wear.ui.LocalToast
import com.deskdot.app.wear.ui.QrBrightness
import com.deskdot.app.wear.ui.Screen
import com.deskdot.app.wear.ui.TextBlockItem
import com.deskdot.app.wear.ui.crownSteps
import com.deskdot.app.wear.ui.rememberConfirm
import com.deskdot.app.wear.ui.rememberTextInput
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.File

// ============================================================================ engine helpers

/** `<filesDir>/deskdot.toml` (read by deskdot.android_main at engine start): only `lan_studio` is touched. */
internal object EngineToml {
    private fun file(ctx: Context) = File(ctx.filesDir, "deskdot.toml")

    fun lanStudio(ctx: Context): Boolean = runCatching {
        file(ctx).takeIf { it.isFile }?.readLines()
            ?.firstOrNull { it.trim().startsWith("lan_studio") }
            ?.substringAfter('=')?.trim()?.startsWith("true") ?: false
    }.getOrDefault(false)

    fun setLanStudio(ctx: Context, on: Boolean) {
        runCatching {
            val f = file(ctx)
            val lines = if (f.isFile) f.readLines().toMutableList() else mutableListOf()
            val i = lines.indexOfFirst { it.trim().startsWith("lan_studio") }
            val line = "lan_studio = $on"
            if (i >= 0) {
                lines[i] = line
            } else {
                // top-level keys must come before the first [table]
                val t = lines.indexOfFirst { it.trim().startsWith("[") }
                if (t >= 0) lines.add(t, line) else lines.add(line)
            }
            f.writeText(lines.joinToString("\n") + "\n")
        }
    }
}

/** Start / stop / restart the engine's foreground service (EngineService is shared with the phone, unchanged). */
internal object EngineControl {
    fun stop(ctx: Context, dd: Dd) {
        runCatching { ctx.stopService(Intent(ctx, EngineService::class.java)) }
        dd.engine.markDown()
    }

    fun start(ctx: Context) = runCatching { EngineService.start(ctx) }

    suspend fun restart(ctx: Context, dd: Dd): Boolean {
        stop(ctx, dd)
        delay(1500)
        start(ctx)
        return dd.engine.awaitReady(90_000)
    }
}

private fun pssMb(ctx: Context): Int = runCatching {
    val am = ctx.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
    am.getProcessMemoryInfo(intArrayOf(Process.myPid()))[0].totalPss / 1024
}.getOrDefault(0)

private suspend fun hostInfo(dd: Dd): HostInfo? = dd.engine.get("/api/host")?.let { HostInfo(it.optString("lan_ip", ""), it.optInt("port", 8765)) }

private fun statusWord(connected: Boolean, connecting: Boolean) = when {
    connected -> "Connected"
    connecting -> "Connecting"
    else -> "Offline"
}

// ================================================================================== §5.1.1 More

@Composable
fun MorePage(nav: NavHostController, pager: PagerState) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    val ctx = LocalContext.current
    val active = pager.active(4)
    LiveState(active)
    val state by dd.engine.state.collectAsState()
    val readiness by dd.engine.readiness.collectAsState()
    var ram by remember { mutableIntStateOf(0) }
    var ip by remember { mutableStateOf("") }
    var lan by remember { mutableStateOf(false) }
    LaunchedEffect(active) {
        if (!active) return@LaunchedEffect
        ram = pssMb(ctx)
        lan = EngineToml.lanStudio(ctx)
        hostInfo(dd)?.let { h -> ip = if (h.onLan) h.lanIp else "" }
    }
    val scope = rememberCoroutineScope()
    val msg = rememberTextInput("Message") { text ->
        scope.launch {
            val hex = String.format("#%06x", look.roles.accent.toArgb() and 0xFFFFFF)
            val ok = dd.engine.post("/api/text", JSONObject().put("text", text).put("color", hex).put("revert_after", 15)) != null
            if (ok) { haptics.confirm(); toast.show("Sent to panel") } else { haptics.reject(); toast.show("Engine not reachable") }
        }
    }
    val s = state
    val list = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus, active)
    Box(Modifier.fillMaxSize()) {
        SuiteList(list, focus) {
            item("h") { HeaderItem(it, "More") }
            item("panel") {
                val d = s?.device
                val v = if (d == null) "—" else "${d.name ?: d.address ?: "No panel"} · ${statusWord(d.connected, d.connecting)}"
                SettingItem(it, Icons.link, "Panel", v, onClick = { nav.navigate(Route.PANEL) })
            }
            item("display") {
                val v = if (s == null) "—" else "${s.brightness}%" + if (s.night.enabled) " · Night ${s.night.start}" else ""
                SettingItem(it, Icons.display, "Display", v, onClick = { nav.navigate(Route.DISPLAY) })
            }
            item("engine") {
                val v = when (readiness) {
                    Readiness.Ready -> "Running · $ram MB" + if (ip.isNotEmpty()) " · $ip" else ""
                    Readiness.Down -> "Stopped"
                    else -> "Starting…"
                }
                SettingItem(it, Icons.cpu, "Engine", v, onClick = { nav.navigate(Route.ENGINE) })
            }
            item("studio") { SettingItem(it, Icons.qr, "Studio", if (lan) "Shared on LAN" else "Local only", onClick = { nav.navigate(Route.STUDIO) }) }
            item("settings") { SettingItem(it, Icons.gear, "Settings", null, onClick = { nav.navigate(Route.SETTINGS) }) }
            item("acts") {
                ActionRowItem(
                    it,
                    listOf(
                        Act(Icons.chat, "Msg", "Send a message to the panel") { msg() },
                        Act(Icons.tv, "TV", "TV link") { nav.navigate(Route.TV) },
                    ),
                )
            }
        }
    }
}

// ============================================================================== §5.2b Panel

private fun ago(epochS: Double?): String {
    if (epochS == null) return "—"
    val s = (System.currentTimeMillis() / 1000.0 - epochS).toLong().coerceAtLeast(0)
    return when {
        s < 60 -> "now"
        s < 3600 -> "${s / 60} min"
        s < 86_400 -> "${s / 3600} h"
        else -> "${s / 86_400} d"
    }
}

@Composable
fun PanelScreen(nav: NavHostController) {
    val dd = LocalDd.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    LiveState()
    LaunchedEffect(Unit) { dd.engine.refreshState() }
    val state by dd.engine.state.collectAsState()
    val scope = rememberCoroutineScope()
    val forget = rememberConfirm()
    val d = state?.device
    val list = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(list, focus) {
            item("hero") {
                when {
                    d == null -> HeroItem(it, Icons.sync, Semantic.warn, engineWaitText(), pulse = true)
                    d.connected -> HeroItem(it, Icons.link, Semantic.ok, "Connected")
                    d.connecting -> HeroItem(it, Icons.sync, Semantic.warn, "Connecting…", sub = d.hint, pulse = true)
                    !d.linkEnabled -> HeroItem(it, Icons.linkOff, Semantic.error, "Released", sub = "The panel is free for other devices.")
                    else -> HeroItem(it, Icons.linkOff, Semantic.error, "Offline", sub = d.hint)
                }
            }
            if (d != null) {
                item("name") { DataRowItem(it, "Name", d.name ?: "—") }
                item("addr") {
                    val a = d.address
                    DataRowItem(it, "Address", a?.let { x -> "…" + x.takeLast(8) } ?: "—", onClick = { if (a != null) toast.show(a) })
                }
                item("rssi") { DataRowItem(it, "Signal", d.rssi?.let { r -> "−${-r} dBm" } ?: "—") }
                item("fps") { DataRowItem(it, "Link fps", String.format("%.1f", d.linkFps)) }
                item("drop") { DataRowItem(it, "Dropped", d.framesDropped.toString()) }
                item("seen") { DataRowItem(it, "Last seen", ago(d.lastSeen)) }
                item("acts") {
                    ActionRowItem(
                        it,
                        listOf(
                            Act(Icons.sync, "Retry", "Reconnect") {
                                scope.launch { if (dd.engine.post("/api/device/reconnect") != null) haptics.confirm() else haptics.reject() }
                            },
                            if (d.linkEnabled) {
                                Act(Icons.linkOff, "Release", "Release the panel") {
                                    scope.launch { dd.engine.post("/api/device/link", JSONObject().put("enabled", false)); haptics.confirm(); dd.engine.refreshState() }
                                }
                            } else {
                                Act(Icons.link, "Use", "Use the panel here") {
                                    scope.launch { dd.engine.post("/api/device/link", JSONObject().put("enabled", true)); haptics.confirm(); dd.engine.refreshState() }
                                }
                            },
                            Act(Icons.close, if (forget.armed) "Sure?" else "Forget", "Forget this panel", variant = if (forget.armed) Btn.Error else Btn.Neutral) {
                                forget.tap(scope) {
                                    scope.launch {
                                        dd.engine.delete("/api/device/address")
                                        dd.engine.post("/api/device/link", JSONObject().put("enabled", false))
                                        haptics.confirm()
                                        dd.prefs.setOnboarded(false)
                                        nav.rescan()
                                    }
                                }
                            },
                        ),
                    )
                }
                item("change") { GlassPillItem(it, "Change panel", w = 260) { nav.rescan() } }
            }
        }
    }
}

// ============================================================================ §5.8 Display

@Composable
fun DisplayScreen(nav: NavHostController) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    LiveState()
    LaunchedEffect(Unit) { dd.engine.refreshState() }
    val state by dd.engine.state.collectAsState()
    val pager = rememberPagerState { 2 }
    val scope = rememberCoroutineScope()
    var handoff by remember { mutableStateOf("clock") }
    LaunchedEffect(Unit) { dd.engine.get("/api/handoff")?.let { handoff = it.optString("mode", "clock") } }

    fun patch(path: String, body: JSONObject) = dd.scope.launch { dd.engine.patch(path, body); dd.engine.refreshState() }
    fun night(change: (JSONObject) -> Unit) {
        val n = state?.night ?: return
        val o = JSONObject().put("enabled", n.enabled).put("start", n.start).put("end", n.end).put("brightness", n.brightness)
        change(o)
        patch("/api/display", JSONObject().put("night", o))
    }

    Screen {
        VerticalPager(state = pager, modifier = Modifier.fillMaxSize()) { page ->
            if (page == 0) {
                BrightnessGauge(active = pager.currentPage == 0, initial = state?.brightness ?: 60)
            } else {
                val s = state
                val list = rememberSuiteListState()
                val focus = remember { FocusRequester() }
                FocusWhenActive(focus, pager.currentPage == 1)
                SuiteList(list, focus) {
                    item("h") { HeaderItem(it, "Display") }
                    if (s == null) {
                        item("w") { com.deskdot.app.wear.ui.StatusLineItem(it, engineWaitText(), Neutral.onSurfaceVariant) }
                        return@SuiteList
                    }
                    item("power") {
                        SettingItem(it, Icons.power, "Panel power", null, if (s.power) Trailing.SwitchOn else Trailing.SwitchOff, onClick = {
                            haptics.confirm(); patch("/api/settings", JSONObject().put("power", !s.power))
                        })
                    }
                    item("night") {
                        SettingItem(it, Icons.moon, "Night mode", if (s.night.enabled) "${s.night.start}–${s.night.end}" else null, if (s.night.enabled) Trailing.SwitchOn else Trailing.SwitchOff, onClick = {
                            haptics.confirm(); night { o -> o.put("enabled", !s.night.enabled) }
                        })
                    }
                    if (s.night.enabled) {
                        listOf("start" to "Starts", "end" to "Ends").forEach { (key, title) ->
                            item("n_$key") {
                                val cur = if (key == "start") s.night.start else s.night.end
                                SettingItem(it, Icons.hourglass, title, cur, Trailing.Chevron, onClick = {
                                    Pick.number(nav, NumberReq(title, minutes(cur).toDouble(), 0.0, 1435.0, Pick.linear(5.0, 0.0, 1435.0), { v -> hhmm(v.toInt()) }) { v ->
                                        night { o -> o.put(key, hhmm(v.toInt())) }
                                    })
                                })
                            }
                        }
                        item("n_b") {
                            SettingItem(it, Icons.sun, "Night bright", "${s.night.brightness}%", Trailing.Chevron, onClick = {
                                Pick.number(nav, NumberReq("Night brightness", s.night.brightness.toDouble(), 5.0, 100.0, Pick.linear(5.0, 5.0, 100.0), { v -> "${v.toInt()}%" }) { v ->
                                    night { o -> o.put("brightness", v.toInt()) }
                                })
                            })
                        }
                    }
                    item("flip") {
                        SettingItem(it, Icons.rotate, "Rotate 180°", null, if (s.flip) Trailing.SwitchOn else Trailing.SwitchOff, onClick = {
                            haptics.confirm(); patch("/api/settings", JSONObject().put("flip", !s.flip))
                        })
                    }
                    item("trans") {
                        val opts = listOf("cut" to "Cut", "push" to "Push", "fade" to "Fade", "wipe" to "Wipe")
                        SettingItem(it, Icons.swap, "Transition", opts.firstOrNull { o -> o.first == s.transition }?.second ?: s.transition, Trailing.Chevron, onClick = {
                            Pick.choice(nav, ChoiceReq("Transition", opts, s.transition) { v -> patch("/api/settings", JSONObject().put("transition", v)) })
                        })
                    }
                    item("fps") {
                        SettingItem(it, Icons.speed, "Max fps", fmtFps(s.maxFps), Trailing.Chevron, onClick = {
                            Pick.number(nav, NumberReq("Max fps", s.maxFps, 0.5, 30.0, Pick.linear(0.5, 0.5, 30.0), ::fmtFps) { v ->
                                patch("/api/display", JSONObject().put("max_fps", v))
                            })
                        })
                    }
                    item("handoff") {
                        val opts = listOf("clock" to "Clock", "app" to "App", "last" to "Last")
                        SettingItem(it, Icons.handoff, "Hand-off", opts.firstOrNull { o -> o.first == handoff }?.second ?: handoff, Trailing.Chevron, onClick = {
                            Pick.choice(nav, ChoiceReq("Hand-off on exit", opts, handoff) { v ->
                                handoff = v
                                dd.scope.launch { dd.engine.put("/api/handoff", JSONObject().put("mode", v)) }
                            })
                        })
                    }
                }
            }
        }
        Spacer(
            Modifier.fillMaxSize().drawBehind {
                drawCircle(if (pager.currentPage == 0) Neutral.onSurface else Neutral.outline, 3f, Offset(398f, 196f))
                drawCircle(if (pager.currentPage == 1) Neutral.onSurface else Neutral.outline, 3f, Offset(398f, 220f))
            },
        )
    }
}

private fun fmtFps(v: Double) = if (v == Math.floor(v)) "${v.toInt()} fps" else "$v fps"
private fun minutes(hhmm: String) = runCatching { hhmm.substringBefore(':').toInt() * 60 + hhmm.substringAfter(':').toInt() }.getOrDefault(0)
private fun hhmm(m: Int) = String.format("%02d:%02d", (m / 60) % 24, m % 60)

/**
 * §5.8 brightness gauge: arc r 164 (stroke 16, round caps, 270° from −135°), value 80 px + "%" 40 px ink-centred
 * at baseline 214, "Panel brightness" at 246 (the reserved slot for the −5% / +5% on-press labels), −/+ glass
 * circles at (160, 300) / (256, 300). Crown ±5 % (5–100) with CLOCK_TICK, REJECT at the ends; PATCH debounced 150 ms.
 */
@Composable
private fun BrightnessGauge(active: Boolean, initial: Int) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val scope = rememberCoroutineScope()
    var v by remember { mutableIntStateOf(initial) }
    var touched by remember { mutableStateOf(false) }
    LaunchedEffect(initial) { if (!touched) v = initial }
    var job by remember { mutableStateOf<Job?>(null) }
    var slot by remember { mutableStateOf<String?>(null) }
    var slotJob by remember { mutableStateOf<Job?>(null) }
    val slotAlpha = remember { androidx.compose.animation.core.Animatable(0f) }
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus, active)

    fun step(d: Int) {
        val n = (v + 5 * d).coerceIn(5, 100)
        if (n == v) { haptics.reject(); return }
        haptics.tick()
        v = n
        touched = true
        slot = if (d > 0) "+5%" else "−5%"
        slotJob?.cancel()
        slotJob = scope.launch {
            slotAlpha.animateTo(1f, look.motion.tween(120, Ease.standardDecel))
            delay(1200)
            slotAlpha.animateTo(0f, look.motion.tween(150, Ease.standardAccel))
        }
        job?.cancel()
        job = scope.launch {
            delay(150)
            dd.engine.patch("/api/settings", JSONObject().put("brightness", v))
        }
    }

    Box(Modifier.fillMaxSize().crownSteps(focus) { step(it) }.semantics { contentDescription = "Panel brightness $v percent" }) {
        Spacer(
            Modifier.fillMaxSize().drawWithCache {
                val num = textRun(v.toString(), TStyle(OFont.G600.bumped(look.bold), 80f, tnum = true))
                val pct = textRun("%", TStyle(OFont.G600.bumped(look.bold), 40f))
                val label = textRun("Panel brightness", TS.labelM(look.bold))
                val ctl = textRun(slot ?: "", TS.labelCtl)
                onDrawBehind {
                    val st = Stroke(16f, cap = StrokeCap.Round)
                    drawArc(if (look.le) Neutral.outline else Neutral.surface2, 135f, 270f, false, Offset(44f, 44f), Size(328f, 328f), style = st)
                    drawArc(look.roles.accent, 135f, 270f * (v - 5) / 95f, false, Offset(44f, 44f), Size(328f, 328f), style = st)
                    val x0 = 208f - (num.inkLeft + num.advance + pct.inkRight) / 2f
                    drawRun(num, x0, 214f, Neutral.onSurface)
                    drawRun(pct, x0 + num.advance, 214f, Neutral.onSurface)
                    val a = slotAlpha.value
                    if (a < 1f) drawRun(label, 208f, 246f, look.variantText, TAlign.InkCenter, 1f - a)
                    if (a > 0f) drawRun(ctl, 208f, 246f, Neutral.onSurface, TAlign.InkCenter, a)
                }
            },
        )
        GlassButton(Modifier.pxAt(160 - 48, 300 - 48, 96, 96), Icons.remove, "Dimmer", iconSize = 40f) { step(-1) }
        GlassButton(Modifier.pxAt(256 - 48, 300 - 48, 96, 96), Icons.add, "Brighter", iconSize = 40f) { step(1) }
    }
}

// ============================================================================== §5.9 Engine

@Composable
fun EngineScreen() {
    val dd = LocalDd.current
    val ctx = LocalContext.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    LiveState()
    val state by dd.engine.state.collectAsState()
    val readiness by dd.engine.readiness.collectAsState()
    val version by dd.engine.version.collectAsState()
    val stats = remember { DeviceStats(ctx) }
    var cpu by remember { mutableStateOf<Double?>(null) }
    var ram by remember { mutableIntStateOf(0) }
    var temp by remember { mutableStateOf<Double?>(null) }
    var drain by remember { mutableStateOf<Double?>(null) }
    var host by remember { mutableStateOf<HostInfo?>(null) }
    var busy by remember { mutableStateOf(false) }
    val stop = rememberConfirm()
    val scope = rememberCoroutineScope()
    val lifecycle = LocalLifecycleOwner.current
    // CPU / RAM / temperature sampled every 2 s, only while this screen is on.
    LaunchedEffect(lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            dd.engine.probe(2_000)
            host = hostInfo(dd)
            stats.cpuPercent()
            while (true) {
                delay(2_000)
                cpu = stats.cpuPercent()
                ram = stats.ramMb()
                temp = stats.batteryTempC()
                stats.drainPercentPerHour()?.let { drain = it }
            }
        }
    }
    val up = (SystemClock.elapsedRealtime() - Process.getStartElapsedRealtime()) / 60_000
    val upText = if (up >= 60) "${up / 60} h ${up % 60} m" else "$up m"
    val list = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(list, focus) {
            item("hero") {
                when {
                    busy -> HeroItem(it, Icons.sync, Semantic.warn, "Restarting…", pulse = true)
                    readiness == Readiness.Ready -> HeroItem(it, Icons.check, Semantic.ok, "Running · $upText")
                    readiness == Readiness.Down -> HeroItem(it, Icons.power, Semantic.error, "Stopped")
                    else -> HeroItem(it, Icons.sync, Semantic.warn, "Starting…", pulse = true)
                }
            }
            if (readiness == Readiness.Down && !busy) item("start") {
                GlassPillItem(it, "Start", accent = true) {
                    busy = true
                    EngineControl.start(ctx)
                    scope.launch { dd.engine.awaitReady(90_000); busy = false }
                }
            }
            item("v") { DataRowItem(it, "Version", version.ifEmpty { "—" }) }
            item("r") { DataRowItem(it, "Render", state?.let { s -> String.format("%.1f ms", s.renderMs) } ?: "—") }
            item("l") { DataRowItem(it, "Link", state?.let { s -> String.format("%.1f fps", s.device.linkFps) } ?: "—") }
            item("c") { DataRowItem(it, "CPU", cpu?.let { c -> String.format("%.0f %%", c) } ?: "—") }
            item("m") { DataRowItem(it, "RAM", if (ram > 0) "$ram MB" else "—", if (ram >= 170) Semantic.warn else Neutral.onSurface) }
            if (ram >= 170) item("mh") { com.deskdot.app.wear.ui.StatusLineItem(it, "Memory high", Semantic.warn) }
            item("ip") { DataRowItem(it, "LAN IP", host?.let { h -> if (h.onLan) h.lanIp else "No Wi-Fi" } ?: "—") }
            item("port") { DataRowItem(it, "Port", (host?.port ?: 8765).toString()) }
            item("t") { DataRowItem(it, "Battery", temp?.let { t -> String.format("%.1f °C", t) } ?: "—", if ((temp ?: 0.0) >= 41.0) Semantic.warn else Neutral.onSurface) }
            item("d") { DataRowItem(it, "Drain", drain?.let { x -> String.format("%+.0f %%/h", x).replace('-', '−') } ?: "—") }
            item("acts") {
                ActionRowItem(
                    it,
                    listOf(
                        Act(Icons.restart, "Restart", "Restart the engine", enabled = !busy) {
                            busy = true
                            haptics.confirm()
                            scope.launch {
                                val ok = EngineControl.restart(ctx, dd)
                                busy = false
                                toast.show(if (ok) "Engine restarted" else "Engine didn't start")
                            }
                        },
                        Act(Icons.power, if (stop.armed) "Sure?" else "Stop", "Stop the engine", variant = if (stop.armed) Btn.Error else Btn.Neutral, enabled = readiness != Readiness.Down) {
                            stop.tap(scope) {
                                haptics.confirm()
                                EngineControl.stop(ctx, dd)
                            }
                        },
                    ),
                )
            }
        }
    }
}

// =============================================================================== §5.10 Studio

@Composable
fun StudioScreen() {
    val dd = LocalDd.current
    val look = LocalLook.current
    val ctx = LocalContext.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    val scope = rememberCoroutineScope()
    var mode by remember { mutableStateOf(0) } // 0 menu, 1 share QR, 2 web view
    var lan by remember { mutableStateOf(EngineToml.lanStudio(ctx)) }
    var host by remember { mutableStateOf<HostInfo?>(null) }
    var restarting by remember { mutableStateOf(false) }
    var dimmed by remember { mutableStateOf(false) }
    val hasWebView = remember { runCatching { androidx.webkit.WebViewCompat.getCurrentWebViewPackage(ctx) != null }.getOrDefault(false) }
    LaunchedEffect(Unit) { host = hostInfo(dd) }
    androidx.activity.compose.BackHandler(enabled = mode != 0) { mode = 0 }

    when (mode) {
        1 -> {
            val h = host
            val hostWifi by dd.prefs.hostWifi.collectAsState()
            DisposableEffect(hostWifi) {
                val lease = WifiLease(ctx)
                if (hostWifi) lease.acquire()
                onDispose { lease.release() }
            }
            QrBrightness(enabled = !dimmed, maxMs = if (look.calm) 120_000 else 300_000) { dimmed = true }
            if (h != null && h.onLan) {
                val url = "http://${h.lanIp}:${h.port}/"
                QrPageLayer(
                    url, "${h.lanIp}:${h.port}", "Studio", hint = if (dimmed) "Tap to brighten" else null,
                    modifier = Modifier
                        .semantics { contentDescription = "Studio address ${h.lanIp} port ${h.port}" }
                        .pointerInput(Unit) { detectTapGestures { dimmed = false } },
                )
            } else {
                Screen {
                    WarnCardItem(Modifier.pxAt(43, 140, 330, 108), "Connect the watch to Wi-Fi to share the studio")
                }
            }
        }
        2 -> AndroidView(
            factory = { c ->
                android.webkit.WebView(c).apply {
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    setInitialScale(50)
                    loadUrl("http://127.0.0.1:8765")
                }
            },
            modifier = Modifier.fillMaxSize(),
        )
        else -> {
            val list = rememberSuiteListState()
            val focus = remember { FocusRequester() }
            FocusWhenActive(focus)
            Screen {
                SuiteList(list, focus) {
                    item("h") { HeaderItem(it, "Studio", sub = if (lan) "Shared on LAN" else "Local only") }
                    if (!lan) {
                        item("off") { TextBlockItem(it, "Studio sharing is off.") }
                        item("on") {
                            GlassPillItem(it, if (restarting) "Restarting…" else "Turn on", accent = true, enabled = !restarting) {
                                EngineToml.setLanStudio(ctx, true)
                                lan = true
                                restarting = true
                                haptics.confirm()
                                scope.launch {
                                    val ok = EngineControl.restart(ctx, dd)
                                    restarting = false
                                    toast.show(if (ok) "Studio shared" else "Engine didn't start")
                                }
                            }
                        }
                    }
                    if (!hasWebView) item("nowv") { TextBlockItem(it, "This watch has no web view. Use Share to open the studio on your phone.", maxLines = 4) }
                    item("acts") {
                        ActionRowItem(
                            it,
                            buildList {
                                add(Act(Icons.qr, "Share", "Share the studio QR", enabled = lan) { dimmed = false; mode = 1 })
                                if (hasWebView) add(Act(Icons.openNew, "Open", "Open the studio here") { mode = 2 })
                            },
                        )
                    }
                }
            }
        }
    }
}
