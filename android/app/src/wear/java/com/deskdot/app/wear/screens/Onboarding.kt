package com.deskdot.app.wear.screens

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.navigation.NavHostController
import com.deskdot.app.EngineService
import com.deskdot.app.wear.ble.PanelCandidate
import com.deskdot.app.wear.ble.WearBleScanner
import com.deskdot.app.wear.design.DrawnItem
import com.deskdot.app.wear.design.HeaderItem
import com.deskdot.app.wear.design.Icons
import com.deskdot.app.wear.design.LocalHaptics
import com.deskdot.app.wear.design.LocalLook
import com.deskdot.app.wear.design.Neutral
import com.deskdot.app.wear.design.OFont
import com.deskdot.app.wear.design.Semantic
import com.deskdot.app.wear.design.SuiteList
import com.deskdot.app.wear.design.TAlign
import com.deskdot.app.wear.design.TS
import com.deskdot.app.wear.design.TStyle
import com.deskdot.app.wear.design.drawIcon
import com.deskdot.app.wear.design.drawRun
import com.deskdot.app.wear.design.pxAt
import com.deskdot.app.wear.design.rememberSuiteListState
import com.deskdot.app.wear.design.rowPress
import com.deskdot.app.wear.design.textRun
import com.deskdot.app.wear.nav.Route
import com.deskdot.app.wear.nav.connect
import com.deskdot.app.wear.nav.home
import com.deskdot.app.wear.net.Readiness
import com.deskdot.app.wear.ui.Act
import com.deskdot.app.wear.ui.ActionRowItem
import com.deskdot.app.wear.ui.FocusWhenActive
import com.deskdot.app.wear.ui.GlassPillItem
import com.deskdot.app.wear.ui.LocalDd
import com.deskdot.app.wear.ui.LocalToast
import com.deskdot.app.wear.ui.PillPair
import com.deskdot.app.wear.ui.ScanArc
import com.deskdot.app.wear.ui.Screen
import com.deskdot.app.wear.ui.StatusLineItem
import com.deskdot.app.wear.ui.TextBlockItem
import com.deskdot.app.wear.ui.rememberTextInput
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

// ============================================================================ §5.2a step 1: Welcome

@Composable
fun WelcomeScreen(nav: NavHostController) {
    val look = LocalLook.current
    val ctx = LocalContext.current
    Screen {
        Spacer(
            Modifier.fillMaxSize().drawWithCache {
                val t = textRun("DeskDot", TS.titleL(look.bold))
                val s = textRun("Let's find your panel", TS.bodyL(look.bold), 330f)
                onDrawBehind {
                    drawRun(t, 208f, 150f, Neutral.onSurface, TAlign.InkCenter)
                    drawRun(s, 208f, 190f, look.variantText, TAlign.InkCenter)
                }
            },
        )
        // "Find panel": glass accent-text pill 240 x 80 centred at (208, 280).
        GlassPillItem(Modifier.pxAt(88, 232, 240, 96), "Find panel", accent = true) {
            val granted = ctx.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
            nav.navigate(if (granted) Route.SCAN else Route.PERMS)
        }
    }
}

// ======================================================================== §5.2a step 2: Permissions

@Composable
fun PermissionsScreen(nav: NavHostController) {
    val ctx = LocalContext.current
    val dd = LocalDd.current
    val haptics = LocalHaptics.current
    var denied by remember { mutableStateOf(false) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { res ->
        if (res[Manifest.permission.ACCESS_FINE_LOCATION] == true) {
            EngineService.start(ctx)
            if (dd.prefs.onboarded.value) nav.home() else nav.navigate(Route.SCAN) { popUpTo(Route.PERMS) { inclusive = true } }
        } else {
            denied = true
            haptics.reject()
        }
    }
    val state = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(state, focus) {
            item("h") { HeaderItem(it, "Bluetooth") }
            item("t") {
                TextBlockItem(it, "Bluetooth needs location to find the panel. Nothing leaves the watch.", maxLines = 4)
            }
            if (denied) {
                item("w") { WarnCardItem(it, "Location is off for DeskDot, so it can't find panels.") }
                item("s") {
                    GlassPillItem(it, "Open settings", w = 260) {
                        runCatching {
                            ctx.startActivity(
                                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + ctx.packageName))
                                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                            )
                        }
                    }
                }
            }
            item("a") {
                GlassPillItem(it, "Allow", accent = true) {
                    launcher.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION))
                }
            }
        }
    }
}

/** §1.12 amber warning card: fill #2A2208, 2 px border warn @ 50%, on-surface text (14.2:1). */
@Composable
fun WarnCardItem(modifier: Modifier, text: String) {
    val look = LocalLook.current
    val lines = remember(text, look.bold) { com.deskdot.app.wear.ui.wrap(text, TS.body26(look.bold), 280f, 4) }
    val h = 40 + lines.size * 34
    DrawnItem(modifier, 330, h, description = text) {
        val runs = lines.map { textRun(it, TS.body26(look.bold)) }
        onDrawBehind {
            drawRoundRect(Color(0xFF2A2208), cornerRadius = CornerRadius(28f))
            drawRoundRect(Semantic.warn.copy(alpha = 0.5f), Offset(1f, 1f), Size(size.width - 2f, size.height - 2f), CornerRadius(27f), style = Stroke(2f))
            runs.forEachIndexed { i, r -> drawRun(r, size.width / 2f, 46f + i * 34f, Neutral.onSurface, TAlign.InkCenter) }
        }
    }
}

// ========================================================================== §5.2a step 3: Scan list

private enum class ScanPhase { Waiting, Scanning, Done, BluetoothOff }

/** Screenshot tests only: show these panels as a scan in progress instead of using the radio. */
internal var scanPreview: List<PanelCandidate>? = null

@SuppressLint("MissingPermission")
@Composable
fun ScanScreen(nav: NavHostController) {
    val ctx = LocalContext.current
    val dd = LocalDd.current
    val look = LocalLook.current
    val toast = LocalToast.current
    val haptics = LocalHaptics.current
    val scope = rememberCoroutineScope()
    val found = remember { mutableStateListOf<PanelCandidate>() }
    var phase by remember { mutableStateOf(ScanPhase.Waiting) }
    var round by remember { mutableIntStateOf(0) }
    val lifecycle = LocalLifecycleOwner.current

    LaunchedEffect(round, lifecycle) {
        scanPreview?.let { p ->
            found.clear(); found.addAll(p); phase = ScanPhase.Scanning
            return@LaunchedEffect
        }
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            val adapter = ctx.getSystemService(BluetoothManager::class.java)?.adapter
            if (adapter == null || !adapter.isEnabled) {
                phase = ScanPhase.BluetoothOff
                return@repeatOnLifecycle
            }
            phase = ScanPhase.Scanning
            // Free the radio: the engine stops its own reconnect attempts while the watch scans (§5.2a).
            scope.launch {
                if (dd.engine.awaitReady(4_000)) dd.engine.post("/api/device/link", JSONObject().put("enabled", false))
            }
            withTimeoutOrNull(10_000) {
                WearBleScanner(ctx).scan().collect { list ->
                    found.clear()
                    found.addAll(list)
                }
            }
            phase = ScanPhase.Done
            if (found.isNotEmpty()) haptics.confirm()
        }
    }

    val manual = rememberTextInput("Panel address") { raw ->
        val mac = normaliseMac(raw)
        if (mac == null) {
            haptics.reject()
            toast.show("Not a panel address")
        } else {
            nav.connect(mac, mac)
        }
    }

    val state = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(state, focus) {
            item("h") {
                HeaderItem(it, if (look.le && phase == ScanPhase.Scanning) "Scanning…" else "Panels")
            }
            when {
                phase == ScanPhase.BluetoothOff -> {
                    item("off") { TextBlockItem(it, "Bluetooth is off.") }
                    item("on") {
                        GlassPillItem(it, "Turn on", accent = true) {
                            @Suppress("DEPRECATION")
                            val ok = runCatching { ctx.getSystemService(BluetoothManager::class.java)?.adapter?.enable() == true }.getOrDefault(false)
                            if (ok) {
                                scope.launch { delay(1200); round++ }
                            } else {
                                runCatching { ctx.startActivity(Intent(Settings.ACTION_BLUETOOTH_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                            }
                        }
                    }
                }
                found.isEmpty() && phase == ScanPhase.Done -> {
                    item("none") { TextBlockItem(it, "No panels found. Is the panel on and nearby?") }
                    item("again") { GlassPillItem(it, "Scan again") { round++ } }
                }
                else -> items(found.toList(), key = { it.address }) { c, m ->
                    ScanRowItem(m, c) { nav.connect(c.address, c.name) }
                }
            }
            item("acts") {
                ActionRowItem(
                    it,
                    listOf(
                        Act(Icons.btScan, "Scan", "Scan for panels", enabled = phase != ScanPhase.Scanning) { round++ },
                        Act(Icons.keyboard, "MAC", "Enter the panel address") { manual() },
                    ),
                )
            }
        }
        ScanArc(visible = phase == ScanPhase.Scanning)
    }
}

/** preview `scanList` row: h 120; bt icon at −136, name at −100, 3 signal bars + "−58 dBm" on the second line. */
@Composable
private fun ScanRowItem(modifier: Modifier, c: PanelCandidate, onClick: () -> Unit) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val bars = when {
        c.rssi >= -65 -> 3
        c.rssi >= -78 -> 2
        else -> 1
    }
    val dbm = "−${-c.rssi} dBm"
    DrawnItem(
        modifier, 352, 120, description = "${c.name}, signal $bars of 3",
        press = rowPress(look, 352f, 120f, haptics), onClick = onClick,
    ) {
        val n = textRun(c.name, TS.titleM(look.bold), 250f)
        val d = textRun(dbm, TS.body26(look.bold))
        onDrawBehind {
            val cy = size.height / 2f
            drawIcon(Icons.bluetooth, 40f, cy, 40f, look.variantText)
            drawRun(n, 76f, cy - 6f, Neutral.onSurface)
            for (i in 0 until 3) {
                val h = 6f + i * 6f
                drawRoundRect(
                    look.variantText, Offset(76f + i * 9f, cy + 30f - h), Size(6f, h), CornerRadius(1f),
                    alpha = if (i < bars) 1f else 0.25f,
                )
            }
            drawRun(d, 110f, cy + 30f, look.variantText)
        }
    }
}

/** "aabbccddeeff" or "AA-BB-…" → "AA:BB:CC:DD:EE:FF", or null when it isn't a MAC. */
internal fun normaliseMac(raw: String): String? {
    val hex = raw.uppercase().filter { it.isDigit() || it in 'A'..'F' }
    if (hex.length != 12) return null
    return hex.chunked(2).joinToString(":")
}

// ===================================================================== §5.2a step 4: Connecting / HI

private enum class Link { Starting, Connecting, Connected, Failed }

@Composable
fun ConnectScreen(nav: NavHostController, addr: String, name: String) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val readiness by dd.engine.readiness.collectAsState()
    var link by remember { mutableStateOf(Link.Starting) }
    var hint by remember { mutableStateOf<String?>(null) }
    var attempt by remember { mutableIntStateOf(0) }
    val lifecycle = LocalLifecycleOwner.current

    LaunchedEffect(attempt, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            link = Link.Starting
            if (!dd.engine.awaitReady(60_000)) {
                link = Link.Failed
                hint = "The DeskDot engine isn't running."
                return@repeatOnLifecycle
            }
            link = Link.Connecting
            dd.engine.acquireSocket()
            try {
                dd.engine.put("/api/device/address", JSONObject().put("address", addr))
                dd.engine.post("/api/device/link", JSONObject().put("enabled", true))
                // Wait up to 25 s for the link: the state push normally tells us; when the socket isn't up, ask.
                val deadline = android.os.SystemClock.elapsedRealtime() + 25_000
                var ok: com.deskdot.app.wear.net.EngineState? = null
                while (ok == null && android.os.SystemClock.elapsedRealtime() < deadline) {
                    val s0 = if (dd.engine.socketUp.value) dd.engine.state.value else dd.engine.refreshState()
                    if (s0?.device?.connected == true && (s0.device.address == null || s0.device.address.equals(addr, true))) ok = s0
                    else withTimeoutOrNull(1_000) { dd.engine.state.first { it?.device?.connected == true } }
                }
                if (ok != null) {
                    link = Link.Connected
                    haptics.confirm()
                    dd.engine.post(
                        "/api/text",
                        JSONObject().put("text", "HI").put("color", hex(look.roles.accent)).put("revert_after", 3),
                    )
                } else {
                    link = Link.Failed
                    hint = dd.engine.state.value?.device?.hint ?: dd.engine.refreshState()?.device?.hint
                    haptics.reject()
                }
                kotlinx.coroutines.awaitCancellation()
            } finally {
                dd.engine.releaseSocket()
            }
        }
    }

    val color = when (link) {
        Link.Connected -> Semantic.ok
        Link.Failed -> Semantic.error
        else -> Semantic.warn
    }
    val icon = when (link) {
        Link.Connected -> Icons.link
        Link.Failed -> Icons.linkOff
        else -> Icons.sync
    }
    val title = when (link) {
        Link.Starting -> if (readiness == Readiness.Down) "Engine off" else "Starting…"
        Link.Connecting -> "Connecting…"
        Link.Connected -> "Connected"
        Link.Failed -> "Couldn't connect"
    }
    val pulse = remember { Animatable(1f) }
    val doPulse = (link == Link.Connecting || link == Link.Starting) && !look.le && !look.motion.cut
    LaunchedEffect(doPulse) {
        if (doPulse) pulse.animateTo(0.4f, infiniteRepeatable(tween(500, easing = LinearEasing), RepeatMode.Reverse)) else pulse.snapTo(1f)
    }
    val question = link == Link.Connected
    val failed = link == Link.Failed
    val hintLines = remember(hint, look.bold) { hint?.let { com.deskdot.app.wear.ui.wrap(it, TS.body26(look.bold), 300f, 2) }.orEmpty() }

    Screen {
        // preview `connecting`: ring (208,118) r 62 stroke 4, 64 px icon, title-m baseline 222, line at 266.
        Spacer(
            Modifier.fillMaxSize().drawWithCache {
                val t = textRun(title, TS.titleM(look.bold), 330f)
                val q1 = textRun("Do you see ", TS.body26(look.bold))
                val q2 = textRun("HI", TStyle(OFont.G700, 26f))
                val q3 = textRun(" on the panel?", TS.body26(look.bold))
                val nameRun = textRun(name.ifEmpty { addr }, TS.body26(look.bold), 300f)
                val hints = hintLines.map { textRun(it, TS.body26(look.bold)) }
                onDrawBehind {
                    drawCircle(color, 62f, Offset(208f, 118f), alpha = pulse.value, style = Stroke(4f))
                    drawIcon(icon, 208f, 118f, 64f, color)
                    drawRun(t, 208f, 222f, Neutral.onSurface, TAlign.InkCenter)
                    when {
                        question -> {
                            val w = q1.advance + q2.advance + q3.advance
                            var x = 208f - w / 2f
                            drawRun(q1, x, 266f, look.variantText); x += q1.advance
                            drawRun(q2, x, 266f, Neutral.onSurface); x += q2.advance
                            drawRun(q3, x, 266f, look.variantText)
                        }
                        failed -> hints.forEachIndexed { i, r -> drawRun(r, 208f, 262f + i * 32f, look.variantText, TAlign.InkCenter) }
                        else -> drawRun(nameRun, 208f, 266f, look.variantText, TAlign.InkCenter)
                    }
                }
            },
        )
        when {
            question -> PillPair(
                Modifier.pxAt(32, 284, 352, 88), "Yes", "No",
                onLeft = {
                    dd.prefs.setOnboarded(true)
                    haptics.confirm()
                    nav.home()
                },
                onRight = { nav.popBackStack() },
            )
            failed -> Box(Modifier.pxAt(32, if (hintLines.size > 1) 312 else 290, 352, 88)) {
                PillPair(Modifier, "Retry", "Other", leftAccent = true, onLeft = { attempt++ }, onRight = { nav.popBackStack() })
            }
        }
    }
}

private fun hex(c: Color): String = String.format("#%06x", c.toArgb() and 0xFFFFFF)
