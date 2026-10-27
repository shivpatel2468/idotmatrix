package com.deskdot.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Keeps DeskDot running: a foreground service (persistent notification) that starts the Python engine once and
 * holds a partial wake lock and a Wi-Fi lock, so the panel keeps playing and the studio / phone controllers stay
 * reachable with the screen off. Started by [MainActivity] and at boot by [BootReceiver].
 *
 * The watch (`R.bool.is_watch`) holds them only while the engine needs them (docs/adr/0014): the engine reports its
 * power demand through [onPowerDemand] - the wake lock while a panel is linked or a client on another device is
 * connected, the Wi-Fi lock and the Wi-Fi network request while a lobby / TV link is open or such a client is
 * connected. Idle (no panel, nothing hosted) it holds nothing and the watch sleeps; the panel coming back wakes it
 * through BleBridge's standby connect. The phone keeps both locks for the service's whole life, as before.
 */
class EngineService : Service() {
    companion object {
        private const val TAG = "DeskDot"
        private const val CHANNEL = "engine"
        private const val NOTE_ID = 1
        const val PORT = 8765

        /** Watch only: hold the CPU while the Python engine starts (~30 s there) and reports its first demand. */
        private const val STARTUP_HOLD_MS = 120_000L

        @Volatile var engineRunning = false
            private set

        @Volatile private var instance: EngineService? = null

        /**
         * Called from Python (deskdot.android_main) on the engine thread whenever the engine's power demand changes:
         * [wake] = keep the CPU awake, [wifi] = keep the Wi-Fi radio up and routed to for LAN hosting.
         */
        @JvmStatic
        fun onPowerDemand(wake: Boolean, wifi: Boolean) {
            instance?.applyDemand(wake, wifi)
        }

        fun start(context: Context) {
            val i = Intent(context, EngineService::class.java)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(i) else context.startService(i)
        }
    }

    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var wifiNetworkCallback: ConnectivityManager.NetworkCallback? = null
    private val main = Handler(Looper.getMainLooper())
    private var isWatch = false
    private var wifiWanted = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        isWatch = resources.getBoolean(R.bool.is_watch)
        instance = this
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.channel_engine), NotificationManager.IMPORTANCE_LOW).apply {
                description = getString(R.string.channel_engine_desc)
                setShowBadge(false)
            },
        )
        val note = notification(getString(R.string.note_starting))
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTE_ID, note, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(NOTE_ID, note)
        }
        wakeLock = getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DeskDot::engine")
            .apply { setReferenceCounted(false) }
        @Suppress("DEPRECATION")
        val mode = if (Build.VERSION.SDK_INT >= 29) WifiManager.WIFI_MODE_FULL_LOW_LATENCY else WifiManager.WIFI_MODE_FULL_HIGH_PERF
        wifiLock = (applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager)
            .createWifiLock(mode, "DeskDot::studio")
            .apply { setReferenceCounted(false) }
        if (isWatch) {
            wakeLock?.acquire(STARTUP_HOLD_MS) // until the engine's first demand report (applyDemand) decides
        } else {
            wakeLock?.acquire()
            wifiLock?.acquire()
        }
        startEngine()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    private fun startEngine() {
        if (engineRunning) return
        engineRunning = true
        BleBridge.init(applicationContext, lowPower = isWatch)
        Thread({
            // The engine runs until the service is destroyed; if it ever crashes, restart it after a pause.
            while (engineRunning) {
                try {
                    if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
                    update(getString(R.string.note_running))
                    Python.getInstance().getModule("deskdot.android_main")
                        .callAttr("run", filesDir.absolutePath, PORT, isWatch)
                } catch (t: Throwable) {
                    Log.e(TAG, "engine stopped", t)
                    update(getString(R.string.note_error, t.message ?: t.javaClass.simpleName))
                }
                if (engineRunning) Thread.sleep(10_000)
            }
        }, "deskdot-engine").start()
    }

    /** The engine's power demand (see the class doc). Watch only: the phone keeps its locks for the service's life. */
    private fun applyDemand(wake: Boolean, wifi: Boolean) {
        main.post {
            if (!isWatch || instance !== this) return@post
            val wl = wakeLock ?: return@post
            if (wake) wl.acquire() else if (wl.isHeld) wl.release() // acquire() also cancels the start-up timeout
            if (wifi != wifiWanted) {
                wifiWanted = wifi
                if (wifi) {
                    wifiLock?.acquire()
                    requestWifiNetwork()
                } else {
                    wifiLock?.let { if (it.isHeld) it.release() }
                    releaseWifiNetwork()
                }
            }
            Log.i(TAG, "power demand: wake lock ${if (wake) "held" else "released"}, wi-fi ${if (wifi) "held" else "released"}")
        }
    }

    /**
     * Wear OS: left to itself, the watch drops its Wi-Fi radio and routes IP traffic over the Bluetooth proxy to
     * the paired phone as soon as the screen sleeps — fine for browsing, fatal for LAN hosting (the studio over
     * Wi-Fi, multiplayer controllers joining `/p/<code>`). Requesting (and holding) a Wi-Fi network with internet
     * capability keeps the radio associated and routes through it instead, while the engine hosts (see
     * [applyDemand]). [WifiManager.WifiLock] alone is not enough on Wear OS for this.
     */
    private fun requestWifiNetwork() {
        if (wifiNetworkCallback != null) return
        val cm = getSystemService(ConnectivityManager::class.java) ?: return
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .build()
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Log.i(TAG, "Wi-Fi network available for LAN hosting: $network")
                try {
                    cm.bindProcessToNetwork(network) // route the engine's sockets over Wi-Fi, not the BT proxy
                } catch (t: Throwable) {
                    Log.w(TAG, "bindProcessToNetwork: $t")
                }
            }

            override fun onLost(network: Network) {
                Log.w(TAG, "Wi-Fi network lost: $network")
            }
        }
        try {
            cm.requestNetwork(request, cb)
            wifiNetworkCallback = cb
        } catch (t: Throwable) {
            Log.w(TAG, "requestNetwork: $t")
        }
    }

    private fun releaseWifiNetwork() {
        val cb = wifiNetworkCallback ?: return
        wifiNetworkCallback = null
        val cm = getSystemService(ConnectivityManager::class.java) ?: return
        try {
            cm.unregisterNetworkCallback(cb)
            cm.bindProcessToNetwork(null) // back to the default route (the BT proxy while the screen sleeps)
        } catch (t: Throwable) {
            Log.w(TAG, "releaseWifiNetwork: $t")
        }
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        engineRunning = false
        try {
            if (Python.isStarted()) Python.getInstance().getModule("deskdot.android_main").callAttr("stop")
        } catch (t: Throwable) {
            Log.w(TAG, "stop: $t")
        }
        wakeLock?.let { if (it.isHeld) it.release() }
        wifiLock?.let { if (it.isHeld) it.release() }
        releaseWifiNetwork()
        super.onDestroy()
    }

    private fun update(text: String) {
        getSystemService(NotificationManager::class.java).notify(NOTE_ID, notification(text))
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_deskdot)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .build()
    }
}
