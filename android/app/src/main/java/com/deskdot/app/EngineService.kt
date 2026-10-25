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
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Keeps DeskDot running: a foreground service (persistent notification) that starts the Python engine once and
 * holds a partial wake lock and a Wi-Fi lock, so the panel keeps playing and the studio / phone controllers stay
 * reachable with the screen off. Started by [MainActivity] and at boot by [BootReceiver].
 */
class EngineService : Service() {
    companion object {
        private const val TAG = "DeskDot"
        private const val CHANNEL = "engine"
        private const val NOTE_ID = 1
        const val PORT = 8765

        @Volatile var engineRunning = false
            private set

        fun start(context: Context) {
            val i = Intent(context, EngineService::class.java)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(i) else context.startService(i)
        }
    }

    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var wifiNetworkCallback: ConnectivityManager.NetworkCallback? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        if (resources.getBoolean(R.bool.is_watch)) requestWifiNetwork()
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
            .apply { setReferenceCounted(false); acquire() }
        @Suppress("DEPRECATION")
        val mode = if (Build.VERSION.SDK_INT >= 29) WifiManager.WIFI_MODE_FULL_LOW_LATENCY else WifiManager.WIFI_MODE_FULL_HIGH_PERF
        wifiLock = (applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager)
            .createWifiLock(mode, "DeskDot::studio")
            .apply { setReferenceCounted(false); acquire() }
        startEngine()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    private fun startEngine() {
        if (engineRunning) return
        engineRunning = true
        BleBridge.init(applicationContext)
        Thread({
            // The engine runs until the service is destroyed; if it ever crashes, restart it after a pause.
            while (engineRunning) {
                try {
                    if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
                    update(getString(R.string.note_running))
                    Python.getInstance().getModule("deskdot.android_main").callAttr("run", filesDir.absolutePath, PORT)
                } catch (t: Throwable) {
                    Log.e(TAG, "engine stopped", t)
                    update(getString(R.string.note_error, t.message ?: t.javaClass.simpleName))
                }
                if (engineRunning) Thread.sleep(10_000)
            }
        }, "deskdot-engine").start()
    }

    /**
     * Wear OS: left to itself, the watch drops its Wi-Fi radio and routes IP traffic over the Bluetooth proxy to
     * the paired phone as soon as the screen sleeps — fine for browsing, fatal for LAN hosting (the studio over
     * Wi-Fi, multiplayer controllers joining `/p/<code>`). Requesting (and holding) a Wi-Fi network with internet
     * capability keeps the radio associated and routes through it instead, for as long as the engine runs.
     * [WifiManager.WifiLock] alone (already held above, for the phone too) is not enough on Wear OS for this.
     */
    private fun requestWifiNetwork() {
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

    override fun onDestroy() {
        engineRunning = false
        try {
            if (Python.isStarted()) Python.getInstance().getModule("deskdot.android_main").callAttr("stop")
        } catch (t: Throwable) {
            Log.w(TAG, "stop: $t")
        }
        wakeLock?.release()
        wifiLock?.release()
        wifiNetworkCallback?.let {
            try {
                getSystemService(ConnectivityManager::class.java)?.unregisterNetworkCallback(it)
            } catch (t: Throwable) {
                Log.w(TAG, "unregisterNetworkCallback: $t")
            }
        }
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
