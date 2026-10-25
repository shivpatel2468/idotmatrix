package com.deskdot.app.wear.screens

import androidx.compose.foundation.layout.Column
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
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ListHeader
import androidx.wear.compose.material.Text
import com.deskdot.app.wear.net.EngineClient
import com.deskdot.app.wear.ui.ScrollScaffold
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/**
 * DESIGN_SPEC §5.2a first-run onboarding, simplified to a single scan + connect flow (the full 4-screen wizard
 * with a dedicated Welcome / Permissions step is not built in this pass — MainActivity already requests the
 * runtime BLE/location permissions before this Composable is shown, so step 2 is effectively handled upstream).
 *
 * Scanning here calls `GET /api/device/scan`, which on `device=android` returns `[]` per DESIGN_SPEC §5.0 ("it
 * adds a native scan API... because GET /api/device/scan returns [] on Android"); the native
 * `BluetoothLeScanner` scan from BleBridge that the spec calls for is NOT wired into this screen yet (see the
 * final report) — entering a MAC manually via "Enter address" always works as a fallback.
 */
@Composable
fun OnboardingScreen(engine: EngineClient, onPaired: () -> Unit) {
    var candidates by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var connecting by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        val arr = engine.getArray("/api/device/scan")
        candidates = (0 until arr.length()).map { arr.getJSONObject(it) }
    }

    ScrollScaffold {
        item { ListHeader { Text("Find your panel") } }
        if (candidates.isEmpty()) {
            item { Text("No panels found yet.") }
        }
        items(candidates.size) { i ->
            val c = candidates[i]
            Chip(
                label = { Text(c.optString("name", c.optString("address"))) },
                secondaryLabel = { Text("${c.optInt("rssi", 0)} dBm") },
                onClick = {
                    val address = c.optString("address")
                    connecting = address
                    scope.launch {
                        engine.put("/api/device/address", JSONObject().put("address", address))
                        engine.post("/api/text", JSONObject().put("text", "HI").put("color", "#ff4818").put("revert_after", 3))
                        onPaired()
                    }
                },
            )
        }
        item {
            Chip(
                label = { Text("Scan again") },
                onClick = {
                    scope.launch {
                        val arr = engine.getArray("/api/device/scan")
                        candidates = (0 until arr.length()).map { arr.getJSONObject(it) }
                    }
                },
            )
        }
    }
}
