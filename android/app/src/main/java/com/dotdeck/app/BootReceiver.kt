package com.dotdeck.app

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build

/** Start DotDeck when the phone boots (or the app is updated), so the panel comes back without touching it. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        val bt = if (Build.VERSION.SDK_INT >= 31) Manifest.permission.BLUETOOTH_CONNECT else Manifest.permission.ACCESS_FINE_LOCATION
        // a connectedDevice foreground service may only start once Bluetooth permission was granted in the app
        if (context.checkSelfPermission(bt) == PackageManager.PERMISSION_GRANTED) EngineService.start(context)
    }
}
