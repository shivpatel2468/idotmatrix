package com.deskdot.app

import android.app.AlarmManager
import android.app.PendingIntent
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.wifi.WifiManager
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import com.chaquo.python.Python

/**
 * Pure decisions, kept apart so they read (and could be tested) without Android (ADR 0016).
 */
object PowerPolicy {
    data class Locks(val wake: Boolean, val wifi: Boolean, val multicast: Boolean)

    /**
     * Which locks to hold. `busy` comes from the engine (deskdot/keepawake.py); the app on screen always keeps it awake.
     * The multicast lock (to hear other DeskDots' beacons) is held only while the hand-over setting is on and someone
     * may be looking (the screen is on) or a hand-over / pairing is running. Beacons are still *sent* without it, and
     * release requests from other DeskDots arrive over plain HTTP, so a laptop can always take the panel.
     */
    fun locks(busy: Boolean, appVisible: Boolean, screenOn: Boolean, lan: Boolean, discovery: Boolean): Locks {
        val awake = busy || appVisible
        return Locks(wake = awake, wifi = awake, multicast = lan && (screenOn || discovery))
    }

    /** Scan hard only while the user is watching the app; Android throttles everything else anyway. */
    fun scanMode(screenOn: Boolean, appVisible: Boolean): Int = when {
        screenOn && appVisible -> ScanSettings.SCAN_MODE_LOW_LATENCY
        screenOn -> ScanSettings.SCAN_MODE_BALANCED
        else -> ScanSettings.SCAN_MODE_LOW_POWER
    }

    /** A low-power scan listens ~10 % of the time: give it longer to hear the panel. */
    fun scanMillis(mode: Int): Long = if (mode == ScanSettings.SCAN_MODE_LOW_LATENCY) 10_000L else 20_000L

    /** Seconds until the next alarm while asleep, clamped (Android defers idle alarms to ~9 min in Doze anyway). */
    fun alarmSeconds(wakeIn: Int): Int = wakeIn.coerceIn(5, 3600)
}

/**
 * The phone's power for the engine (ADR 0016). [EngineService] calls [init]; the Python engine calls [report] whenever
 * its verdict changes; [MainActivity] reports whether the app is on screen. While the engine is "asleep" this holds no
 * wake, Wi-Fi or multicast lock — the BLE link stays up in the Bluetooth stack — and sets an alarm for the engine's
 * next look (a reconnect attempt, a clip re-bake): [NudgeReceiver] then holds a short wake lock and wakes the engine.
 */
object PowerGate {
    private const val TAG = "DeskDotPower"
    private const val NUDGE_HOLD_MS = 25_000L

    private var context: Context? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var nudgeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var multicastLock: WifiManager.MulticastLock? = null
    private var screenReceiver: BroadcastReceiver? = null

    // Until the engine's first report: awake, as before (the engine is starting and connecting)
    @Volatile private var busy = true
    @Volatile private var discovery = false
    @Volatile private var lan = true
    @Volatile private var wakeIn = 900
    @Volatile private var reason = "starting"
    @Volatile private var screenOn = true
    @Volatile private var appVisible = false

    @Synchronized
    fun init(ctx: Context) {
        if (context != null) return
        val app = ctx.applicationContext
        context = app
        val pm = app.getSystemService(PowerManager::class.java)
        screenOn = pm.isInteractive
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DeskDot::engine").apply { setReferenceCounted(false) }
        nudgeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DeskDot::nudge").apply { setReferenceCounted(false) }
        val wifi = app.getSystemService(Context.WIFI_SERVICE) as WifiManager
        @Suppress("DEPRECATION")
        val mode = if (Build.VERSION.SDK_INT >= 29) WifiManager.WIFI_MODE_FULL_LOW_LATENCY else WifiManager.WIFI_MODE_FULL_HIGH_PERF
        wifiLock = wifi.createWifiLock(mode, "DeskDot::studio").apply { setReferenceCounted(false) }
        // Other DeskDots announce who holds the panel with UDP broadcasts (ADR 0015); phones filter them without this.
        multicastLock = wifi.createMulticastLock("DeskDot::handover").apply { setReferenceCounted(false) }
        val r = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) {
                screenOn = i.action == Intent.ACTION_SCREEN_ON
                apply()
                nudgeEngine()
            }
        }
        screenReceiver = r
        // system broadcasts only: no export flag needed
        app.registerReceiver(r, IntentFilter().apply { addAction(Intent.ACTION_SCREEN_ON); addAction(Intent.ACTION_SCREEN_OFF) })
        apply()
    }

    @Synchronized
    fun shutdown() {
        val app = context ?: return
        screenReceiver?.let { runCatching { app.unregisterReceiver(it) } }
        screenReceiver = null
        cancelAlarm(app)
        for (l in listOf(wakeLock, nudgeLock)) if (l?.isHeld == true) l.release()
        if (wifiLock?.isHeld == true) wifiLock?.release()
        if (multicastLock?.isHeld == true) multicastLock?.release()
        context = null
    }

    // ------------------------------------------------------------------ called from Python (deskdot/keepawake.py)

    @JvmStatic
    fun report(engineBusy: Boolean, discovery: Boolean, lan: Boolean, wakeInSeconds: Int, why: String) {
        busy = engineBusy
        this.discovery = discovery
        this.lan = lan
        wakeIn = wakeInSeconds
        reason = why
        apply()
    }

    @JvmStatic
    fun isScreenOn(): Boolean = screenOn

    @JvmStatic
    fun isAppVisible(): Boolean = appVisible && screenOn

    // ------------------------------------------------------------------ the app

    fun setAppVisible(visible: Boolean) {
        if (appVisible == visible) return
        appVisible = visible
        apply()
        nudgeEngine()
    }

    /** The alarm fired: hold the CPU a moment and wake the engine's event loop so its overdue timers run. */
    fun onAlarm() {
        nudgeLock?.acquire(NUDGE_HOLD_MS)
        nudgeEngine()
        apply() // re-arms the alarm if the engine stays asleep
    }

    @Synchronized
    private fun apply() {
        val app = context ?: return
        val want = PowerPolicy.locks(busy, appVisible && screenOn, screenOn, lan, discovery)
        set(wakeLock, want.wake)
        wifiLock?.let { if (want.wifi && !it.isHeld) it.acquire() else if (!want.wifi && it.isHeld) it.release() }
        multicastLock?.let {
            if (want.multicast && !it.isHeld) it.acquire() else if (!want.multicast && it.isHeld) it.release()
        }
        if (want.wake) cancelAlarm(app) else scheduleAlarm(app, PowerPolicy.alarmSeconds(wakeIn))
        Log.i(TAG, "wake=${want.wake} wifi=${want.wifi} multicast=${want.multicast} ($reason; screen=$screenOn app=$appVisible)")
    }

    private fun set(lock: PowerManager.WakeLock?, on: Boolean) {
        lock ?: return
        if (on && !lock.isHeld) lock.acquire() else if (!on && lock.isHeld) lock.release()
    }

    private fun alarmIntent(app: Context): PendingIntent = PendingIntent.getBroadcast(
        app, 0, Intent(app, NudgeReceiver::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun scheduleAlarm(app: Context, seconds: Int) {
        val am = app.getSystemService(AlarmManager::class.java)
        // inexact and Doze-friendly: no exact-alarm permission, at most one per ~9 min in deep Doze
        am.setAndAllowWhileIdle(
            AlarmManager.ELAPSED_REALTIME_WAKEUP, SystemClock.elapsedRealtime() + seconds * 1000L, alarmIntent(app),
        )
    }

    private fun cancelAlarm(app: Context) {
        app.getSystemService(AlarmManager::class.java).cancel(alarmIntent(app))
    }

    private fun nudgeEngine() {
        Thread({
            try {
                if (Python.isStarted()) Python.getInstance().getModule("deskdot.keepawake").callAttr("nudge")
            } catch (t: Throwable) {
                Log.d(TAG, "nudge: $t")
            }
        }, "deskdot-nudge").start()
    }
}

/** The engine's alarm (see [PowerGate.onAlarm]). */
class NudgeReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        PowerGate.onAlarm()
    }
}
