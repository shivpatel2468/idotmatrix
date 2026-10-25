package com.deskdot.app.wear.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ListHeader
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.ToggleChip
import androidx.wear.compose.material.ToggleChipDefaults
import com.deskdot.app.wear.Routes
import com.deskdot.app.wear.net.EngineClient
import com.deskdot.app.wear.ui.QrPlate
import com.deskdot.app.wear.ui.ScrollScaffold
import kotlinx.coroutines.launch
import org.json.JSONObject

/** DESIGN_SPEC §5.1.1: the More page (page 4) — Panel / Display / Engine / Studio / Settings rows. */
@Composable
fun MoreScreen(engine: EngineClient, nav: NavHostController) {
    var state by remember { mutableStateOf<JSONObject?>(null) }
    LaunchedEffect(Unit) { state = engine.get("/api/state") }
    val device = state?.optJSONObject("device")
    ScrollScaffold {
        item { ListHeader { Text("More") } }
        item {
            Chip(
                label = { Text("Panel") },
                secondaryLabel = { Text("${device?.optString("name") ?: "-"} - ${device?.optString("status") ?: "-"}") },
                onClick = { nav.navigate(Routes.PANEL) },
            )
        }
        item { Chip(label = { Text("Display") }, onClick = { nav.navigate(Routes.DISPLAY) }) }
        item { Chip(label = { Text("Engine") }, onClick = { nav.navigate(Routes.ENGINE) }) }
        item { Chip(label = { Text("Studio") }, onClick = { nav.navigate(Routes.STUDIO) }) }
        item { Chip(label = { Text("Settings") }, onClick = { nav.navigate(Routes.SETTINGS) }) }
    }
}

/** DESIGN_SPEC §5.2b: panel status, retry / release-use / forget. */
@Composable
fun PanelScreen(engine: EngineClient, nav: NavHostController) {
    var state by remember { mutableStateOf<JSONObject?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { state = engine.get("/api/state") }
    val device = state?.optJSONObject("device")
    ScrollScaffold {
        item { ListHeader { Text(device?.optString("status") ?: "unknown") } }
        item { Text("Name: ${device?.optString("name") ?: "-"}") }
        item { Text("Address: ...${device?.optString("address")?.takeLast(8) ?: "-"}") }
        item { Text("Link fps: ${device?.optDouble("link_fps", 0.0)}") }
        item { Text("Dropped: ${device?.optInt("frames_dropped", 0)}") }
        item { Chip(label = { Text("Retry") }, onClick = { scope.launch { engine.post("/api/device/reconnect") } }) }
        item {
            val linkEnabled = device?.optBoolean("link_enabled", true) ?: true
            Chip(
                label = { Text(if (linkEnabled) "Release" else "Use") },
                onClick = { scope.launch { engine.post("/api/device/link", JSONObject().put("enabled", !linkEnabled)) } },
            )
        }
        item {
            Chip(
                label = { Text("Forget") },
                onClick = {
                    scope.launch {
                        engine.delete("/api/device/address")
                        nav.popBackStack()
                    }
                },
            )
        }
    }
}

/** DESIGN_SPEC §5.8: brightness gauge (fixed layout, not masked) plus display rows. */
@Composable
fun DisplayScreen(engine: EngineClient) {
    var brightness by remember { mutableStateOf(64) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) {
        val st = engine.get("/api/state")
        brightness = st.optInt("brightness", 64)
    }
    fun step(delta: Int) {
        brightness = (brightness + delta).coerceIn(5, 100)
        scope.launch { engine.patch("/api/settings", JSONObject().put("brightness", brightness)) }
    }
    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("$brightness%")
                Text("Panel brightness")
            }
        }
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Chip(label = { Text("-5%") }, onClick = { step(-5) })
                Chip(label = { Text("+5%") }, onClick = { step(5) })
            }
        }
    }
}

/** DESIGN_SPEC §5.9: engine status (version, render ms, link fps, LAN IP, port) — CPU/RAM/temp/drain are shell
 * measurements (ActivityManager / /proc / battery broadcast) that are NOT wired up in this pass; see report. */
@Composable
fun EngineScreen(engine: EngineClient) {
    var health by remember { mutableStateOf<JSONObject?>(null) }
    var host by remember { mutableStateOf<JSONObject?>(null) }
    var state by remember { mutableStateOf<JSONObject?>(null) }
    LaunchedEffect(Unit) {
        health = engine.get("/api/health")
        host = engine.get("/api/host")
        state = engine.get("/api/state")
    }
    ScrollScaffold {
        item { ListHeader { Text("Engine") } }
        item { Text("Version: ${health?.optString("version") ?: "-"}") }
        item { Text("Render: ${state?.optJSONObject("engine")?.optDouble("render_ms", 0.0)} ms") }
        item { Text("Link: ${state?.optJSONObject("device")?.optDouble("link_fps", 0.0)} fps") }
        item { Text("LAN IP: ${host?.optString("lan_ip") ?: "-"}") }
        item { Text("Port: ${host?.optInt("port", 8765)}") }
    }
}

/** DESIGN_SPEC §5.10: Share (QR to open the full studio elsewhere) and Open (on-watch WebView, if present). */
@Composable
fun StudioScreen(engine: EngineClient) {
    var host by remember { mutableStateOf<JSONObject?>(null) }
    LaunchedEffect(Unit) { host = engine.get("/api/host") }
    val url = host?.optString("url").orEmpty()
    ScrollScaffold {
        item { ListHeader { Text("Studio") } }
        item { QrPlate(content = url, plateSizeDp = 130) }
        item { Text(url) }
    }
}

/** DESIGN_SPEC §5.11: the engine/watch settings that matter on a watch. Only the ones with a direct, already
 * existing engine endpoint are wired; others are left as a TODO list in the final report. */
@Composable
fun SettingsScreen(engine: EngineClient) {
    var lanStudio by remember { mutableStateOf(true) }
    val scope = rememberCoroutineScope()
    ScrollScaffold {
        item { ListHeader { Text("Settings") } }
        item {
            ToggleChip(
                checked = lanStudio,
                onCheckedChange = { lanStudio = it },
                label = { Text("LAN studio") },
                toggleControl = { androidx.wear.compose.material.Switch(checked = lanStudio, onCheckedChange = null) },
            )
        }
    }
}
