package com.deskdot.app.wear.host

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import android.os.BatteryManager
import androidx.compose.runtime.Immutable
import androidx.core.app.NotificationCompat
import androidx.wear.ongoing.OngoingActivity
import androidx.wear.ongoing.Status
import com.deskdot.app.MainActivity
import com.deskdot.app.R
import com.deskdot.app.wear.Dd
import com.deskdot.app.wear.net.Lobby
import com.deskdot.app.wear.net.TvLink
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

@Immutable
data class HostSession(val tv: Boolean, val app: String, val appName: String, val code: String, val startedAt: Long)

/**
 * Everything that exists only **while hosting** (§5.0, §5.13, owner Q5):
 *  - the Ongoing Activity chip ("DeskDot · Bomberman"), which reopens the Lobby;
 *  - the optional auto-end (Settings → Auto-end, OFF by default) and a one-time warning at 20% battery;
 *  - a slow (30 s) check that the lobby is still open, so the chip disappears when the studio ends it.
 * Nothing here runs when nothing is hosted: no receiver, no timer, no thread.
 *
 * The engine itself holds the Wi-Fi lock / network request while a lobby or TV link is open (EngineService's
 * power demand); [WifiLease] covers the one LAN use the engine cannot see: the Studio Share QR page.
 */
class Hosting(private val dd: Dd) {
    private val ctx = dd.context
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val _session = MutableStateFlow<HostSession?>(null)
    val session: StateFlow<HostSession?> = _session.asStateFlow()

    private var watchJob: Job? = null
    private var autoEndJob: Job? = null
    private var battery: BroadcastReceiver? = null
    private var warned = false

    /** Called after the watch opened a lobby / TV link, and on app start (to adopt one opened elsewhere). */
    fun started(lobby: Lobby?, tv: TvLink?) {
        val s = when {
            lobby != null -> HostSession(false, lobby.app, dd.meta.value?.name(lobby.app) ?: lobby.app, lobby.code, now())
            tv != null -> HostSession(true, "tv", "TV link", tv.code, now())
            else -> null
        } ?: return ended()
        val prev = _session.value
        _session.value = if (prev != null && prev.code == s.code) prev.copy(appName = s.appName) else s
        post()
        if (watchJob == null) startWatching()
        armAutoEnd()
    }

    /** Everything hosted is closed (or found closed). */
    fun ended() {
        _session.value = null
        watchJob?.cancel(); watchJob = null
        autoEndJob?.cancel(); autoEndJob = null
        battery?.let { runCatching { ctx.unregisterReceiver(it) } }
        battery = null
        warned = false
        ctx.getSystemService(NotificationManager::class.java)?.cancel(NOTE_ID)
        ctx.getSystemService(NotificationManager::class.java)?.cancel(WARN_ID)
    }

    /** Ends hosting from the watch (End, auto-end, the warning's action). */
    suspend fun endNow() {
        val s = _session.value
        if (s == null || !s.tv) dd.engine.delete("/api/play/lobby")
        if (s == null || s.tv) dd.engine.delete("/api/tv")
        ended()
    }

    /** Adopt whatever the engine is hosting right now (app start / resume). */
    suspend fun resync() {
        val l = dd.engine.get("/api/play/lobby") ?: return
        val t = dd.engine.get("/api/tv")
        started(Lobby.parse(l.optJSONObject("lobby")), TvLink.parse(t?.optJSONObject("tv")))
    }

    fun armAutoEnd() {
        autoEndJob?.cancel()
        val mins = dd.prefs.hostAutoEnd.value
        val s = _session.value ?: return
        if (mins <= 0) return
        autoEndJob = scope.launch {
            val left = s.startedAt + mins * 60_000L - now()
            if (left > 0) delay(left)
            endNow()
        }
    }

    private fun startWatching() {
        // Battery: the sticky broadcast fires on every level change while registered — no polling.
        val r = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, i: Intent?) {
                val level = i?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
                val scale = i?.getIntExtra(BatteryManager.EXTRA_SCALE, 100) ?: 100
                val status = i?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
                val charging = status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
                if (level < 0 || scale <= 0) return
                val pct = level * 100 / scale
                if (!warned && !charging && pct <= 20 && _session.value != null) {
                    warned = true
                    warnLowBattery(pct)
                }
            }
        }
        battery = r
        runCatching { ctx.registerReceiver(r, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) }
        watchJob = scope.launch {
            while (isActive) {
                delay(30_000)
                val s = _session.value ?: break
                val open = if (s.tv) {
                    dd.engine.get("/api/tv")?.let { TvLink.parse(it.optJSONObject("tv")) != null }
                } else {
                    dd.engine.get("/api/play/lobby")?.let { Lobby.parse(it.optJSONObject("lobby")) != null }
                }
                if (open == false) {
                    ended()
                    break
                }
            }
        }
    }

    private fun channel(nm: NotificationManager) {
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Hosting", NotificationManager.IMPORTANCE_LOW))
        }
    }

    private fun openIntent(): PendingIntent = PendingIntent.getActivity(
        ctx, 1,
        Intent(ctx, MainActivity::class.java).putExtra(MainActivity.EXTRA_OPEN, "lobby").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun post() {
        val s = _session.value ?: return
        val nm = ctx.getSystemService(NotificationManager::class.java) ?: return
        channel(nm)
        val text = if (s.tv) "TV link · ${s.code}" else "Hosting ${s.code}"
        val b = NotificationCompat.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_deskdot)
            .setContentTitle("DeskDot · ${s.appName}")
            .setContentText(text)
            .setContentIntent(openIntent())
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        try {
            val status = Status.Builder().addTemplate("DeskDot · ${s.appName}").build()
            OngoingActivity.Builder(ctx, NOTE_ID, b)
                .setStaticIcon(R.drawable.ic_stat_deskdot)
                .setTouchIntent(openIntent())
                .setStatus(status)
                .build()
                .apply(ctx)
        } catch (t: Throwable) {
            // Ongoing Activity unavailable: the plain ongoing notification still works.
        }
        runCatching { nm.notify(NOTE_ID, b.build()) }
    }

    private fun warnLowBattery(pct: Int) {
        val s = _session.value ?: return
        val nm = ctx.getSystemService(NotificationManager::class.java) ?: return
        if (nm.getNotificationChannel(WARN_CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(WARN_CHANNEL, "Hosting battery", NotificationManager.IMPORTANCE_DEFAULT))
        }
        val n = NotificationCompat.Builder(ctx, WARN_CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_deskdot)
            .setContentTitle("Battery $pct%")
            .setContentText("Still hosting ${s.appName}. End it in DeskDot.")
            .setContentIntent(openIntent())
            .setAutoCancel(true)
            .build()
        runCatching { nm.notify(WARN_ID, n) }
    }

    private fun now() = System.currentTimeMillis()

    companion object {
        private const val CHANNEL = "hosting"
        private const val WARN_CHANNEL = "hosting_battery"
        private const val NOTE_ID = 42
        private const val WARN_ID = 43
    }
}

/**
 * Keeps the Wi-Fi radio up and routed while a QR page that other devices will open is on screen
 * (§5.10 Studio Share). Held only between [acquire] and [release]; the screen ties both to its lifecycle.
 */
class WifiLease(context: Context) {
    private val app = context.applicationContext
    private var lock: WifiManager.WifiLock? = null
    private var cb: ConnectivityManager.NetworkCallback? = null

    fun acquire() {
        if (lock != null) return
        try {
            val wm = app.getSystemService(Context.WIFI_SERVICE) as WifiManager
            lock = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_LOW_LATENCY, "DeskDot::share").apply { setReferenceCounted(false); acquire() }
            val cm = app.getSystemService(ConnectivityManager::class.java)
            val c = object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) = Unit
            }
            cm.requestNetwork(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), c)
            cb = c
        } catch (t: Throwable) {
            release()
        }
    }

    fun release() {
        runCatching { lock?.let { if (it.isHeld) it.release() } }
        lock = null
        cb?.let { c -> runCatching { app.getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(c) } }
        cb = null
    }
}
