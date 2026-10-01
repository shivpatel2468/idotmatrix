package com.deskdot.app

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.util.Log
import java.util.UUID

/**
 * The panel's BLE link for the Python engine (src/deskdot/device/android.py holds the contract).
 *
 * One GATT session at a time, driven from a single handler thread. Android allows one GATT operation in flight,
 * which matches the engine: it awaits each write's [BleListener.onWriteDone] before sending the next packet, and
 * it paces packets itself (docs/HARDWARE_PROTOCOL.md). Never disconnects on its own: the panel shows a pairing
 * screen when the link drops, so only the engine's shutdown calls [disconnect].
 */
@SuppressLint("MissingPermission") // MainActivity requests the permissions before the service starts
class BleBridge private constructor(private val context: Context) {
    companion object {
        private const val TAG = "DeskDotBle"
        private val SERVICE_HINT = UUID.fromString("000000fa-0000-1000-8000-00805f9b34fb")
        private val WRITE_UUID = UUID.fromString("0000fa02-0000-1000-8000-00805f9b34fb")
        private val NOTIFY_UUID = UUID.fromString("0000fa03-0000-1000-8000-00805f9b34fb")
        private val CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        private const val SCAN_MS = 10_000L
        private const val DIRECT_MS = 8_000L

        @Volatile private var instance: BleBridge? = null

        fun init(context: Context): BleBridge =
            instance ?: synchronized(this) { instance ?: BleBridge(context.applicationContext).also { instance = it } }

        /** Called from Python: `jclass("com.deskdot.app.BleBridge").getInstance()`. */
        @JvmStatic
        fun getInstance(): BleBridge = checkNotNull(instance) { "BleBridge.init() was not called" }
    }

    private val thread = HandlerThread("deskdot-ble").apply { start() }
    private val handler = Handler(thread.looper)
    private val adapter: BluetoothAdapter? =
        (context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter

    private var listener: BleListener? = null
    private var gatt: BluetoothGatt? = null
    private var writeChar: BluetoothGattCharacteristic? = null
    private var connecting = false
    private var connected = false
    private var mtu = 23
    private var pendingToken = -1
    private var scanning: ScanCallback? = null
    private var attempt = 0 // invalidates timeouts of earlier attempts
    private var direct = false // this attempt is a direct connect by MAC (falls back to a scan)
    private var scanPrefix = "IDM-"
    private var scanAddress: String? = null

    // ------------------------------------------------------------------ API used by Python

    fun connect(address: String?, namePrefix: String, listener: BleListener) {
        handler.post { startConnect(address, namePrefix, listener) }
    }

    fun write(data: ByteArray, withResponse: Boolean, token: Int) {
        handler.post { startWrite(data, withResponse, token, retries = 20) }
    }

    fun disconnect() {
        handler.post {
            attempt++
            stopScan()
            connected = false
            connecting = false
            gatt?.let { it.disconnect(); it.close() }
            gatt = null
            writeChar = null
        }
    }

    /** For the app's notification: "connected to IDM-XXXXXX" etc. */
    val isConnected: Boolean get() = connected

    // ------------------------------------------------------------------ connect: direct by MAC, else scan

    private fun startConnect(address: String?, prefix: String, l: BleListener) {
        listener = l
        val a = adapter
        if (a == null) return fail("this phone has no Bluetooth")
        if (!a.isEnabled) return fail("Bluetooth is off — turn it on in the phone's settings")
        gatt?.close()
        gatt = null
        connected = false
        connecting = true
        val my = ++attempt
        scanPrefix = prefix
        scanAddress = address?.uppercase()?.takeIf { BluetoothAdapter.checkBluetoothAddress(it) }
        val mac = scanAddress
        if (mac != null) {
            // Fast path: the panel's MAC is known (the default config), no scan needed.
            direct = true
            openGatt(a.getRemoteDevice(mac))
            handler.postDelayed({ if (my == attempt && direct && connecting && !connected) fallBackToScan() }, DIRECT_MS)
        } else {
            direct = false
            scan(prefix, null, my)
        }
    }

    private fun fallBackToScan() {
        Log.i(TAG, "direct connect failed, scanning for the panel")
        direct = false
        gatt?.close()
        gatt = null
        scan(scanPrefix, scanAddress, attempt)
    }

    private fun scan(prefix: String, address: String?, my: Int) {
        val scanner = adapter?.bluetoothLeScanner ?: return fail("Bluetooth LE scanner unavailable")
        val cb = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                val dev = result.device
                val name = result.scanRecord?.deviceName ?: dev.name ?: ""
                val match = if (address != null) dev.address.equals(address, true) else name.startsWith(prefix)
                if (match && my == attempt && scanning != null) {
                    stopScan()
                    openGatt(dev)
                }
            }

            override fun onScanFailed(errorCode: Int) {
                if (my == attempt) fail("scan failed ($errorCode)")
            }
        }
        scanning = cb
        val settings = ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build()
        scanner.startScan(null, settings, cb)
        handler.postDelayed({
            if (my == attempt && scanning === cb) {
                stopScan()
                fail("panel not found — is it powered, and not connected to the iDotMatrix phone app?")
            }
        }, SCAN_MS)
    }

    private fun stopScan() {
        val cb = scanning ?: return
        scanning = null
        try {
            adapter?.bluetoothLeScanner?.stopScan(cb)
        } catch (e: Exception) {
            Log.d(TAG, "stopScan: $e")
        }
    }

    private fun openGatt(dev: BluetoothDevice) {
        gatt = dev.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE, BluetoothDevice.PHY_LE_1M_MASK, handler)
    }

    private fun fail(message: String) {
        connecting = false
        listener?.onConnectFailed(message)
    }

    // ------------------------------------------------------------------ writes

    private fun startWrite(data: ByteArray, withResponse: Boolean, token: Int, retries: Int) {
        val g = gatt
        val c = writeChar
        if (!connected || g == null || c == null) {
            listener?.onWriteDone(token, false, "not connected")
            return
        }
        val type = if (withResponse) BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
        else BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
        pendingToken = token
        val started = if (Build.VERSION.SDK_INT >= 33) {
            g.writeCharacteristic(c, data, type) == BluetoothGatt.GATT_SUCCESS
        } else {
            @Suppress("DEPRECATION")
            c.writeType = type
            @Suppress("DEPRECATION")
            c.value = data
            @Suppress("DEPRECATION")
            g.writeCharacteristic(c)
        }
        if (!started) {
            pendingToken = -1
            // the stack is still busy with the previous operation: try again shortly
            if (retries > 0) handler.postDelayed({ startWrite(data, withResponse, token, retries - 1) }, 5)
            else listener?.onWriteDone(token, false, "GATT busy")
        }
    }

    // ------------------------------------------------------------------ GATT callbacks (on our handler thread)

    private val callback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, newState: Int) {
            if (g != gatt) return g.close()
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                g.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)
                if (!g.requestMtu(517)) g.discoverServices()
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                val was = connected
                connected = false
                writeChar = null
                g.close()
                gatt = null
                val tok = pendingToken
                pendingToken = -1
                if (tok >= 0) listener?.onWriteDone(tok, false, "link lost")
                when {
                    was -> listener?.onDisconnected("link lost (GATT status $status)")
                    connecting && direct -> fallBackToScan() // status 133 on a direct connect is common
                    connecting -> fail("connection failed (GATT status $status)")
                }
            }
        }

        override fun onMtuChanged(g: BluetoothGatt, newMtu: Int, status: Int) {
            if (status == BluetoothGatt.GATT_SUCCESS) mtu = newMtu
            g.discoverServices()
        }

        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
            val service = g.services.firstOrNull { it.getCharacteristic(WRITE_UUID) != null }
                ?: g.getService(SERVICE_HINT)
            val w = service?.getCharacteristic(WRITE_UUID)
            if (status != BluetoothGatt.GATT_SUCCESS || w == null) {
                g.disconnect()
                return fail("write characteristic fa02 missing — not an iDotMatrix panel?")
            }
            writeChar = w
            val n = service.getCharacteristic(NOTIFY_UUID)
            val cccd = n?.getDescriptor(CCCD_UUID)
            if (n != null && cccd != null && g.setCharacteristicNotification(n, true)) {
                val ok = if (Build.VERSION.SDK_INT >= 33) {
                    g.writeDescriptor(cccd, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE) == BluetoothGatt.GATT_SUCCESS
                } else {
                    @Suppress("DEPRECATION")
                    cccd.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                    @Suppress("DEPRECATION")
                    g.writeDescriptor(cccd)
                }
                if (ok) return // ready in onDescriptorWrite
            }
            ready(g) // acks are an optimisation: the engine's timeouts cover their absence
        }

        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, status: Int) {
            if (!connected) ready(g)
        }

        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) {
            val tok = pendingToken
            pendingToken = -1
            if (tok >= 0) listener?.onWriteDone(tok, status == BluetoothGatt.GATT_SUCCESS, "GATT status $status")
        }

        @Deprecated("Android < 13")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION")
            if (Build.VERSION.SDK_INT < 33 && c.uuid == NOTIFY_UUID) c.value?.let { listener?.onNotify(it.copyOf()) }
        }

        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) {
            if (c.uuid == NOTIFY_UUID) listener?.onNotify(value)
        }
    }

    private fun ready(g: BluetoothGatt) {
        connecting = false
        connected = true
        val dev = g.device
        val name = dev.name ?: "IDM panel"
        Log.i(TAG, "connected to $name (${dev.address}), mtu $mtu")
        listener?.onConnected(dev.address, name, mtu - 3)
    }
}
