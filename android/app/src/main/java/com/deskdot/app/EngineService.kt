package com.deskdot.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Keeps DeskDot running: a foreground service (persistent notification) that starts the Python engine once. The wake,
 * Wi-Fi and multicast locks are [PowerGate]'s: held while the engine has something to drive, released (with an alarm
 * for the next look) when it hasn't, so the phone can sleep (ADR 0016). Started by [MainActivity] and at boot by
 * [BootReceiver].
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

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
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
        PowerGate.init(applicationContext) // awake until the engine's first report
        startEngine()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    private fun startEngine() {
        if (engineRunning) return
        engineRunning = true
        BleBridge.init(applicationContext)
        Updater.init(applicationContext)
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

    override fun onDestroy() {
        engineRunning = false
        try {
            if (Python.isStarted()) Python.getInstance().getModule("deskdot.android_main").callAttr("stop")
        } catch (t: Throwable) {
            Log.w(TAG, "stop: $t")
        }
        PowerGate.shutdown()
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
