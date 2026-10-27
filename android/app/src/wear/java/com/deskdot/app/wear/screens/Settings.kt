package com.deskdot.app.wear.screens

import android.content.ComponentName
import android.content.pm.PackageManager
import android.os.Build
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.foundation.clickable
import androidx.navigation.NavHostController
import com.deskdot.app.BootReceiver
import com.deskdot.app.wear.data.LeSetting
import com.deskdot.app.wear.data.SuiteSignalSource
import com.deskdot.app.wear.data.SuiteSignals
import com.deskdot.app.wear.design.AccentId
import com.deskdot.app.wear.design.AccentThemes
import com.deskdot.app.wear.design.CaptionItem
import com.deskdot.app.wear.design.GlassFactory
import com.deskdot.app.wear.design.HapticsLevel
import com.deskdot.app.wear.design.HeaderItem
import com.deskdot.app.wear.design.Icons
import com.deskdot.app.wear.design.LocalHaptics
import com.deskdot.app.wear.design.LocalLook
import com.deskdot.app.wear.design.Neutral
import com.deskdot.app.wear.design.PressFeedback
import com.deskdot.app.wear.design.SettingItem
import com.deskdot.app.wear.design.SuiteList
import com.deskdot.app.wear.design.TAlign
import com.deskdot.app.wear.design.TS
import com.deskdot.app.wear.design.Trailing
import com.deskdot.app.wear.design.drawGlass
import com.deskdot.app.wear.design.drawRun
import com.deskdot.app.wear.design.pxAt
import com.deskdot.app.wear.design.rememberSuiteListState
import com.deskdot.app.wear.design.textRun
import com.deskdot.app.wear.nav.ChoiceReq
import com.deskdot.app.wear.nav.NumberReq
import com.deskdot.app.wear.nav.Pick
import com.deskdot.app.wear.nav.Route
import com.deskdot.app.wear.net.EngineClient
import com.deskdot.app.wear.net.objects
import com.deskdot.app.wear.ui.DataRowItem
import com.deskdot.app.wear.ui.FocusWhenActive
import com.deskdot.app.wear.ui.GlassPillItem
import com.deskdot.app.wear.ui.LocalDd
import com.deskdot.app.wear.ui.LocalToast
import com.deskdot.app.wear.ui.Screen
import com.deskdot.app.wear.ui.rememberTextInput
import kotlinx.coroutines.launch
import org.json.JSONObject

private val ADDRESS = Regex("^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?/?$")

/** §5.11: the engine settings that matter on a watch, then the watch's own, Advanced and About. */
@Composable
fun SettingsScreen(nav: NavHostController) {
    val dd = LocalDd.current
    val ctx = LocalContext.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    val scope = rememberCoroutineScope()
    val prefs = dd.prefs
    val bootStart by prefs.bootStart.collectAsState()
    val hostWifi by prefs.hostWifi.collectAsState()
    val autoEnd by prefs.hostAutoEnd.collectAsState()
    val accent by prefs.accent.collectAsState()
    val leMode by prefs.leMode.collectAsState()
    val leTh by prefs.leThreshold.collectAsState()
    val hapticsPref by prefs.haptics.collectAsState()
    val ticks by prefs.crownTicks.collectAsState()
    val fps by prefs.previewFps.collectAsState()
    val addr by prefs.engineAddress.collectAsState()
    val version by dd.engine.version.collectAsState()
    val state by dd.engine.state.collectAsState()
    var lan by remember { mutableStateOf(EngineToml.lanStudio(ctx)) }
    var lanChanged by remember { mutableStateOf(false) }
    var restarting by remember { mutableStateOf(false) }
    var themes by remember { mutableStateOf<List<Pair<String, String>>>(emptyList()) }
    var themeId by remember { mutableStateOf("") }
    val signals = remember { SuiteSignalSource.read(ctx, prefs, SuiteSignals()) }
    LaunchedEffect(Unit) {
        dd.engine.refreshState()
        dd.engine.get("/api/theme")?.let { o ->
            themeId = o.optString("id")
            themes = o.optJSONArray("themes").objects().map { t -> t.optString("id") to t.optString("name", t.optString("id")) }
        }
    }
    val city = rememberTextInput("City") { c ->
        scope.launch {
            val ok = dd.engine.patch("/api/settings", JSONObject().put("location", JSONObject().put("city", c))) != null
            if (ok) { haptics.confirm(); toast.show("Location set"); dd.engine.refreshState() } else { haptics.reject(); toast.show("Engine not reachable") }
        }
    }
    val address = rememberTextInput("Engine address") { a ->
        val v = a.trim()
        if (!ADDRESS.matches(v)) {
            haptics.reject(); toast.show("Not a valid address")
        } else {
            prefs.setEngineAddress(v)
            dd.engine.setBaseUrl(v)
            haptics.confirm()
        }
    }
    val pkgVersion = remember { runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName }.getOrNull() ?: "—" }

    val list = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(list, focus) {
            item("h") { HeaderItem(it, "Settings") }
            item("ce") { CaptionItem(it, "Engine") }
            item("boot") {
                SettingItem(it, Icons.power, "Boot start", null, if (bootStart) Trailing.SwitchOn else Trailing.SwitchOff, onClick = {
                    val on = !bootStart
                    prefs.setBootStart(on)
                    runCatching {
                        ctx.packageManager.setComponentEnabledSetting(
                            ComponentName(ctx, BootReceiver::class.java),
                            if (on) PackageManager.COMPONENT_ENABLED_STATE_ENABLED else PackageManager.COMPONENT_ENABLED_STATE_DISABLED,
                            PackageManager.DONT_KILL_APP,
                        )
                    }
                    haptics.confirm()
                })
            }
            item("lan") {
                SettingItem(it, Icons.openNew, "LAN studio", null, if (lan) Trailing.SwitchOn else Trailing.SwitchOff, onClick = {
                    lan = !lan
                    EngineToml.setLanStudio(ctx, lan)
                    lanChanged = true
                    haptics.confirm()
                    toast.show("Restart engine to apply")
                })
            }
            if (lanChanged) item("restart") {
                GlassPillItem(it, if (restarting) "Restarting…" else "Restart engine", accent = true, w = 300, enabled = !restarting) {
                    restarting = true
                    scope.launch {
                        val ok = EngineControl.restart(ctx, dd)
                        restarting = false
                        lanChanged = !ok
                        toast.show(if (ok) "Engine restarted" else "Engine didn't start")
                    }
                }
            }
            item("wifi") {
                SettingItem(it, Icons.wifi, "Host Wi-Fi", "While hosting", if (hostWifi) Trailing.SwitchOn else Trailing.SwitchOff, onClick = {
                    prefs.setHostWifi(!hostWifi); haptics.confirm()
                })
            }
            item("autoend") {
                val opts = listOf("0" to "Off", "30" to "30 min", "60" to "60 min", "90" to "90 min")
                val cur = opts.firstOrNull { o -> o.first == autoEnd.toString() }?.second ?: "$autoEnd min"
                SettingItem(it, Icons.hourglass, "Auto-end", "$cur · warns at 20%", Trailing.Chevron, onClick = {
                    Pick.choice(nav, ChoiceReq("Auto-end hosting", opts, autoEnd.toString()) { v ->
                        prefs.setHostAutoEnd(v.toInt())
                        dd.hosting.armAutoEnd()
                    })
                })
            }
            if (themes.isNotEmpty()) item("theme") {
                SettingItem(it, Icons.palette, "Page theme", themes.firstOrNull { t -> t.first == themeId }?.second ?: themeId, Trailing.Chevron, onClick = {
                    Pick.choice(nav, ChoiceReq("Page theme", themes, themeId) { v ->
                        themeId = v
                        dd.scope.launch { dd.engine.post("/api/theme", JSONObject().put("id", v)) }
                    })
                })
            }
            item("units") {
                val u = state?.units ?: "metric"
                SettingItem(it, Icons.units, "Units", if (u == "imperial") "Imperial" else "Metric", Trailing.Chevron, onClick = {
                    Pick.choice(nav, ChoiceReq("Units", listOf("metric" to "Metric", "imperial" to "Imperial"), u) { v ->
                        dd.scope.launch { dd.engine.patch("/api/settings", JSONObject().put("units", v)); dd.engine.refreshState() }
                    })
                })
            }
            item("city") { SettingItem(it, Icons.place, "Location", state?.city?.ifEmpty { null } ?: "Not set", Trailing.Chevron, onClick = { city() }) }

            item("cw") { CaptionItem(it, "Watch") }
            item("accent") {
                val name = if (signals.fromOrbit) "From Orbit · ${signals.accent.title}" else runCatching { AccentId.valueOf(accent).title }.getOrDefault("Ember")
                SettingItem(it, Icons.palette, "Accent", name, Trailing.Swatch, swatch = AccentThemes.of(if (signals.fromOrbit) signals.accent else prefs.accentId()).accent, onClick = {
                    if (signals.fromOrbit) toast.show("Change it in Orbit") else nav.navigate(Route.ACCENT)
                })
            }
            item("le") {
                val v = if (signals.fromOrbit) "From Orbit" else "${runCatching { LeSetting.valueOf(leMode).title }.getOrDefault("Auto")} · ≤ $leTh%"
                SettingItem(it, Icons.eco, "Low Energy", v, Trailing.Chevron, onClick = {
                    if (signals.fromOrbit) toast.show("Set in Orbit") else nav.navigate(Route.LOW_ENERGY)
                })
            }
            item("haptics") {
                val cur = runCatching { HapticsLevel.valueOf(hapticsPref) }.getOrDefault(HapticsLevel.Subtle)
                SettingItem(it, Icons.vibration, "Haptics", cur.title, Trailing.Chevron, onClick = {
                    Pick.choice(nav, ChoiceReq("Haptics", HapticsLevel.entries.map { h -> h.name to h.title }, cur.name) { v -> prefs.setHaptics(HapticsLevel.valueOf(v)) })
                })
            }
            item("ticks") {
                SettingItem(
                    it, Icons.vibration, "Crown ticks", if (signals.fromOrbit) "From Orbit" else null,
                    if ((if (signals.fromOrbit) signals.crownTicks else ticks)) Trailing.SwitchOn else Trailing.SwitchOff,
                    onClick = { if (signals.fromOrbit) toast.show("Set in Orbit") else { prefs.setCrownTicks(!ticks); haptics.confirm() } },
                )
            }
            item("fps") {
                SettingItem(it, Icons.speed, "Preview fps", "$fps fps", Trailing.Chevron, onClick = {
                    Pick.choice(nav, ChoiceReq("Live preview", listOf("10" to "10 fps", "5" to "5 fps", "2" to "2 fps"), fps.toString()) { v -> prefs.setPreviewFps(v.toInt()) })
                })
            }

            item("ca") { CaptionItem(it, "Advanced") }
            item("addr") {
                SettingItem(it, Icons.address, "Engine", if (addr.isEmpty()) "This watch" else addr, Trailing.Chevron, onClick = { address() })
            }
            if (addr.isNotEmpty()) item("addr0") {
                GlassPillItem(it, "Reset to this watch", w = 300) {
                    prefs.setEngineAddress("")
                    dd.engine.setBaseUrl(EngineClient.DEFAULT_BASE_URL)
                    haptics.confirm()
                }
            }
            item("test") {
                GlassPillItem(it, "Test connection", w = 300) {
                    scope.launch {
                        val ok = dd.engine.probe(3_000)
                        if (ok) { haptics.confirm(); toast.show("Engine OK · v${dd.engine.version.value}") } else { haptics.reject(); toast.show("No answer") }
                    }
                }
            }

            item("cb") { CaptionItem(it, "About") }
            item("ver") { DataRowItem(it, "DeskDot", pkgVersion) }
            item("eng") { DataRowItem(it, "Engine", version.ifEmpty { "—" }) }
            item("abi") { DataRowItem(it, "ABI", Build.SUPPORTED_ABIS.firstOrNull() ?: "—") }
            item("lic") { DataRowItem(it, "Licences", "OFL", onClick = { toast.show("Google Sans Flex, JetBrains Mono: OFL 1.1") }) }
        }
    }
}

/**
 * §4.9 accent picker (identical to Orbit's): a 2x2 grid of d 96 accent-glass circles at (152, 146), (264, 146),
 * (152, 270), (264, 270); the selected one ringed 4 px on-surface at r 54; the selected (or pressed) theme's name
 * once, in title-m at baseline 360.
 */
@Composable
fun AccentScreen() {
    val dd = LocalDd.current
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val accent by dd.prefs.accent.collectAsState()
    val sel = runCatching { AccentId.valueOf(accent) }.getOrDefault(AccentId.Ember)
    val centres = listOf(152 to 146, 264 to 146, 152 to 270, 264 to 270)
    Screen {
        Spacer(
            Modifier.fillMaxSize().drawWithCache {
                val name = textRun(sel.title, TS.titleM(look.bold))
                onDrawBehind {
                    val (cx, cy) = centres[sel.ordinal]
                    drawCircle(Neutral.onSurface, 54f, Offset(cx.toFloat(), cy.toFloat()), style = Stroke(4f))
                    drawRun(name, 208f, 360f, Neutral.onSurface, TAlign.InkCenter)
                }
            },
        )
        AccentId.entries.forEachIndexed { i, id ->
            val (cx, cy) = centres[i]
            val roles = AccentThemes.of(id)
            val glass = remember(id) { GlassFactory.get(GlassFactory.accentKey(96, 96, 48f, roles, fill = true)) }
            val press = remember(look) { PressFeedback(96f, 96f, 48f, 0.92f, Color(0x1AFFFFFF), look.motion, if (look.le) look.roles.accent else null, null) }
            Box(
                Modifier.pxAt(cx - 50, cy - 50, 100, 100)
                    .semantics { contentDescription = "${id.title} accent${if (id == sel) ", selected" else ""}" }
                    .clickable(interactionSource = remember { MutableInteractionSource() }, indication = press) {
                        dd.prefs.setAccent(id)
                        haptics.confirm()
                    }
                    .drawBehind {
                        if (look.le) drawCircle(roles.accent, 44f, Offset(50f, 50f), style = Stroke(4f)) else drawGlass(glass, 2f, 2f)
                    },
            )
        }
    }
}

/** §4.9 Low Energy sub-screen: Auto / Always / Never and the battery threshold (10–40 % in 5 % steps). */
@Composable
fun LowEnergyScreen(nav: NavHostController) {
    val dd = LocalDd.current
    val haptics = LocalHaptics.current
    val mode by dd.prefs.leMode.collectAsState()
    val th by dd.prefs.leThreshold.collectAsState()
    val list = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(list, focus) {
            item("h") { HeaderItem(it, "Low Energy") }
            LeSetting.entries.forEach { s ->
                item(s.name) {
                    SettingItem(it, null, s.title, null, if (s.name == mode) Trailing.Check else Trailing.None, onClick = {
                        dd.prefs.setLeMode(s); haptics.confirm()
                    })
                }
            }
            item("th") {
                SettingItem(it, Icons.batterySaver, "Threshold", "Battery ≤ $th%", Trailing.Chevron, onClick = {
                    Pick.number(nav, NumberReq("Battery ≤", th.toDouble(), 10.0, 40.0, Pick.linear(5.0, 10.0, 40.0), { v -> "${v.toInt()}%" }) { v -> dd.prefs.setLeThreshold(v.toInt()) })
                })
            }
        }
    }
}
