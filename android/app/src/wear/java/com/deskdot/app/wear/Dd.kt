package com.deskdot.app.wear

import android.content.Context
import android.os.SystemClock
import com.deskdot.app.wear.data.WatchPrefs
import com.deskdot.app.wear.host.Hosting
import com.deskdot.app.wear.net.EngineClient
import com.deskdot.app.wear.net.Meta
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * The DeskDot Watch object graph: one [EngineClient], the prefs, the `/api/meta` cache and the hosting monitor.
 * Shared by the activity, the Tile and the complication (they all live in the engine's process).
 */
class Dd private constructor(val context: Context) {
    val prefs = WatchPrefs(context)
    val engine = EngineClient(prefs.engineAddress.value.ifEmpty { EngineClient.DEFAULT_BASE_URL })
    val hosting = Hosting(this)

    /** Fire-and-forget engine calls that must outlive the screen that started them (pickers, toggles). */
    val scope = kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.SupervisorJob() + kotlinx.coroutines.Dispatchers.Main.immediate)

    /** §2.6 / I-20: the user's max_fps while Calm forces 10 (null when Calm is not overriding it). */
    @Volatile var calmSavedFps: Double? = null

    private val _meta = MutableStateFlow<Meta?>(null)
    val meta: StateFlow<Meta?> = _meta.asStateFlow()
    private var metaAt = 0L
    private val metaLock = Mutex()

    /** §5.4: `/api/meta`, cached for 10 minutes; re-fetched on page entry after that. */
    suspend fun loadMeta(force: Boolean = false): Meta? = metaLock.withLock {
        val now = SystemClock.elapsedRealtime()
        val cached = _meta.value
        if (!force && cached != null && now - metaAt < 10 * 60_000L) return@withLock cached
        if (!engine.awaitReady()) return@withLock cached
        val o = engine.get("/api/meta") ?: return@withLock cached
        val m = runCatching { Meta.parse(o) }.getOrNull() ?: return@withLock cached
        _meta.value = m
        metaAt = now
        m
    }

    companion object {
        @Volatile private var instance: Dd? = null

        fun get(context: Context): Dd = instance ?: synchronized(this) {
            instance ?: Dd(context.applicationContext).also { instance = it }
        }
    }
}
