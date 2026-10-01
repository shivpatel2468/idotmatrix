package com.dotdeck.app

/**
 * Callbacks from [BleBridge] to the Python engine (implemented in Python with Chaquopy's `dynamic_proxy`,
 * see src/dotdeck/device/android.py). Called on the bridge's own thread; the Python side hops onto its event loop.
 */
interface BleListener {
    fun onConnected(address: String, name: String, writeSize: Int)
    fun onConnectFailed(message: String)
    fun onDisconnected(message: String)
    fun onNotify(data: ByteArray)
    fun onWriteDone(token: Int, ok: Boolean, message: String)
}
