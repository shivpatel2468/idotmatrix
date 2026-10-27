package com.deskdot.app.wear.ble

import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow

/** A panel found during onboarding (DESIGN_SPEC §5.2a step 3). */
data class PanelCandidate(val name: String, val address: String, val rssi: Int)

/**
 * The watch's own native BLE scan for onboarding (DESIGN_SPEC §5.0: "It adds a native scan API for the
 * onboarding list, because GET /api/device/scan returns [] on Android"). This mirrors the phone's
 * `BleBridge.kt` `scan()` exactly: `ScanSettings.SCAN_MODE_LOW_LATENCY`, a null `ScanFilter` (Android's
 * ScanFilter only matches a device name *exactly*, not by prefix, so the "IDM-" prefix match happens here,
 * client-side, like the phone does), for 10 s. The BLE link itself is never touched here (CLAUDE.md rule 4) —
 * this only looks for advertisements; connecting happens through `PUT /api/device/address` + the engine's own
 * reconnect, exactly like every other DeskDot client.
 */
class WearBleScanner(private val context: Context) {
    @SuppressLint("MissingPermission") // caller (OnboardingScreen) only starts this once BLUETOOTH_SCAN/location is granted
    fun scan(): Flow<List<PanelCandidate>> = callbackFlow {
        val adapter = context.getSystemService(BluetoothManager::class.java)?.adapter
        val scanner = adapter?.bluetoothLeScanner
        if (adapter == null || !adapter.isEnabled || scanner == null) {
            trySend(emptyList())
            close()
            return@callbackFlow
        }

        val found = LinkedHashMap<String, PanelCandidate>() // address -> candidate, de-duplicated and refreshed
        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                val name = result.scanRecord?.deviceName ?: result.device.name ?: return
                if (!name.startsWith(NAME_PREFIX)) return
                found[result.device.address] = PanelCandidate(name, result.device.address, result.rssi)
                trySend(found.values.sortedByDescending { it.rssi })
            }

            override fun onScanFailed(errorCode: Int) {
                trySend(found.values.sortedByDescending { it.rssi })
            }
        }

        val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
        runCatching { scanner.startScan(null, settings, callback) }

        awaitClose { runCatching { scanner.stopScan(callback) } }
    }

    companion object {
        /** src/deskdot/device/protocol.py NAME_PREFIX — kept in sync by hand (there is no shared constant
         * between the Python engine and this native Kotlin scanner). */
        const val NAME_PREFIX = "IDM-"
    }
}
