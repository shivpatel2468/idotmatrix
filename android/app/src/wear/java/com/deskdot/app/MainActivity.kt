package com.deskdot.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.deskdot.app.wear.Dd
import com.deskdot.app.wear.design.Ink
import com.deskdot.app.wear.design.SuiteFonts
import com.deskdot.app.wear.screens.Signals
import com.deskdot.app.wear.screens.WearRoot

/**
 * DeskDot Watch (DESIGN_SPEC §5): the native Wear Compose UI over the on-watch engine. The engine runs in
 * [EngineService] (shared with the phone flavor, unchanged); this activity only talks to it over
 * http://127.0.0.1:8765 through [com.deskdot.app.wear.net.EngineClient]. The BLE link stays owned by the engine.
 */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SuiteFonts.init(this)
        Ink.fontScale = resources.configuration.fontScale
        Thread({ SuiteFonts.preload() }, "fonts").start()
        val dd = Dd.get(this)
        val granted = hasBlePermission()
        // Location is needed for BLE scans on Android 11; without it the engine could not find the panel.
        if (granted) EngineService.start(this)
        handle(intent)
        setContent { WearRoot(dd, needPermissions = !granted) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private fun handle(i: Intent?) {
        i?.getStringExtra(EXTRA_OPEN)?.let { Signals.open.tryEmit(it) }
    }

    fun hasBlePermission() = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    /** I-13: the pushers (if the system delivers them) are next / previous on Now Playing. */
    override fun onKeyDown(keyCode: Int, event: KeyEvent): Boolean {
        if ((keyCode == KeyEvent.KEYCODE_STEM_1 || keyCode == KeyEvent.KEYCODE_STEM_2) && event.repeatCount == 0) {
            if (Signals.keys.tryEmit(keyCode)) return true
        }
        return super.onKeyDown(keyCode, event)
    }

    companion object {
        const val EXTRA_OPEN = "deskdot.open"
    }
}
