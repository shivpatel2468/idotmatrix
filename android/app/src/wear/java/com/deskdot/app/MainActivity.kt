package com.deskdot.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.wear.compose.material.Text
import com.deskdot.app.wear.WearApp
import com.deskdot.app.wear.net.EngineClient

/**
 * Wear launcher: the native DeskDot Watch UI (DESIGN_SPEC.md §5), replacing the previous full-screen WebView
 * placeholder. Shares [EngineService] and [BleBridge] unchanged with the phone's MainActivity — only this
 * activity differs between the `mobile` and `wear` flavors (android/app/build.gradle.kts).
 *
 * The engine itself is reached over plain HTTP/WebSocket at 127.0.0.1:8765 (EngineClient), exactly like the
 * studio's own JS client (web/src/lib/ws.ts) — never through BleBridge directly: the BLE link is owned
 * exclusively by the engine (CLAUDE.md rule 4).
 */
class MainActivity : ComponentActivity() {
    private val engine = EngineClient()

    private val permissions: Array<String>
        get() = buildList {
            if (Build.VERSION.SDK_INT >= 31) {
                add(Manifest.permission.BLUETOOTH_SCAN)
                add(Manifest.permission.BLUETOOTH_CONNECT)
            } else {
                add(Manifest.permission.ACCESS_FINE_LOCATION)
            }
            if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
        }.toTypedArray()

    private val ask = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        if (result.values.all { it }) EngineService.start(this)
        permissionsGranted = result.values.all { it }
    }

    private var permissionsGranted by mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val missing = permissions.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) {
            EngineService.start(this)
            permissionsGranted = true
        } else {
            ask.launch(missing.toTypedArray())
        }

        setContent {
            if (permissionsGranted) {
                WearApp(engine)
            } else {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(text = getString(R.string.need_bluetooth), color = Color(0xFFF94A18))
                }
            }
        }
    }
}
