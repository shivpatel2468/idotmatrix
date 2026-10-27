package com.deskdot.app.wear.net

import android.os.SystemClock
import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Where the engine is in its start-up, as the UI sees it. */
enum class Readiness { Unknown, Starting, Ready, Down }

/**
 * The single client for the DeskDot engine (REST + the `/ws` push), shared by every screen, the Tile and the
 * complication. Design rules, each one a fix for something seen on the watch:
 *
 *  - **No call path can throw.** Every request returns `null` on any failure (connection refused while the
 *    Chaquopy engine boots, timeouts, HTTP errors, malformed JSON). Only coroutine cancellation propagates.
 *    The startup `ConnectException` crash came from an unguarded call racing EngineService's start.
 *  - **Readiness, not races.** [awaitReady] polls `/api/health` with exponential backoff (250 ms → 2 s) and
 *    publishes [readiness]; callers that need the engine wait on it instead of firing blind.
 *  - **The socket exists only while something visible needs it.** [acquireSocket]/[releaseSocket] are
 *    ref-counted by the screens' lifecycles (RESUMED only). With no holder there is no socket, no reconnect
 *    timer and no thread doing anything: 0% CPU in the background.
 *  - **Latest frame wins.** Binary frames are copied into one reused 3072-byte buffer and a sequence number
 *    is bumped; nothing queues. Drawing code reads the buffer at its own capped rate.
 */
class EngineClient(baseUrl: String = DEFAULT_BASE_URL) {
    @Volatile
    var baseUrl: String = baseUrl.trimEnd('/')
        private set

    private val http = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(8, TimeUnit.SECONDS)
        .writeTimeout(4, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false)
        .build()
    private val jsonMedia = "application/json".toMediaType()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _readiness = MutableStateFlow(Readiness.Unknown)
    val readiness: StateFlow<Readiness> = _readiness.asStateFlow()

    private val _version = MutableStateFlow("")
    val version: StateFlow<String> = _version.asStateFlow()

    private val _state = MutableStateFlow<EngineState?>(null)

    /** The newest `state` push (or a REST refresh); null until the first one. */
    val state: StateFlow<EngineState?> = _state.asStateFlow()

    /** The newest 32x32 RGB frame lives here; read it only after observing [frameSeq]. */
    val frame = ByteArray(FRAME_BYTES)
    private val _frameSeq = MutableStateFlow(0)
    val frameSeq: StateFlow<Int> = _frameSeq.asStateFlow()

    private val _socketUp = MutableStateFlow(false)
    val socketUp: StateFlow<Boolean> = _socketUp.asStateFlow()

    private val socketLock = Any()
    private var socketHolders = 0
    private var socket: WebSocket? = null
    private var reconnectJob: Job? = null
    private var backoffMs = 500L

    private val readyMutex = Mutex()

    fun setBaseUrl(url: String) {
        val clean = url.trim().trimEnd('/').ifEmpty { DEFAULT_BASE_URL }
        if (clean == baseUrl) return
        baseUrl = clean
        _readiness.value = Readiness.Unknown
        synchronized(socketLock) {
            socket?.cancel()
            socket = null
            if (socketHolders > 0) openSocketLocked()
        }
    }

    // ------------------------------------------------------------------------------------------ REST

    private fun req(path: String): Request.Builder? = url(path)?.let { Request.Builder().url(it) }

    suspend fun get(path: String, timeoutMs: Long = 0): JSONObject? {
        val r = req(path) ?: return null
        return call(r.get().build(), timeoutMs)?.asObject()
    }

    suspend fun getArray(path: String): JSONArray? {
        val r = req(path) ?: return null
        return call(r.get().build())?.asArray()
    }

    suspend fun post(path: String, body: JSONObject = JSONObject()): JSONObject? {
        val r = req(path) ?: return null
        return call(r.post(body.toString().toRequestBody(jsonMedia)).build())?.asObject()
    }

    suspend fun put(path: String, body: JSONObject): JSONObject? {
        val r = req(path) ?: return null
        return call(r.put(body.toString().toRequestBody(jsonMedia)).build())?.asObject()
    }

    suspend fun patch(path: String, body: JSONObject): JSONObject? {
        val r = req(path) ?: return null
        return call(r.patch(body.toString().toRequestBody(jsonMedia)).build())?.asObject()
    }

    suspend fun delete(path: String): JSONObject? {
        val r = req(path) ?: return null
        return call(r.delete().build())?.asObject()
    }

    /** True when the engine answered 2xx (for actions whose body we ignore). */
    suspend fun ok(path: String, body: JSONObject = JSONObject(), method: String = "POST"): Boolean {
        val req = Request.Builder().url(url(path) ?: return false)
            .method(method, if (method == "DELETE" && body.length() == 0) null else body.toString().toRequestBody(jsonMedia))
            .build()
        return call(req) != null
    }

    /** Fresh `GET /api/state` (also updates [state]). */
    suspend fun refreshState(): EngineState? {
        val o = get("/api/state") ?: return null
        val s = runCatching { EngineState.parse(o) }.getOrNull() ?: return null
        _state.value = s
        return s
    }

    /** `GET /api/frame` into [frame] (the WebSocket fallback and the Tile). */
    suspend fun pollFrame(timeoutMs: Long = 0): Boolean {
        val o = get("/api/frame", timeoutMs) ?: return false
        val bytes = runCatching { android.util.Base64.decode(o.optString("rgb"), android.util.Base64.DEFAULT) }.getOrNull()
        if (bytes == null || bytes.size < FRAME_BYTES) return false
        synchronized(frame) { System.arraycopy(bytes, 0, frame, 0, FRAME_BYTES) }
        _frameSeq.value = _frameSeq.value + 1
        return true
    }

    private fun url(path: String): String? = (baseUrl + path).takeIf { it.startsWith("http://") || it.startsWith("https://") }

    private suspend fun call(req: Request, timeoutMs: Long = 0): String? = try {
        withContext(Dispatchers.IO) {
            if (timeoutMs > 0) withTimeoutOrNull(timeoutMs) { execute(req) } else execute(req)
        }
    } catch (c: CancellationException) {
        throw c
    } catch (t: Throwable) {
        null
    }

    /** Cancellable OkHttp call: cancelling the coroutine cancels the socket. */
    private suspend fun execute(req: Request): String? = kotlinx.coroutines.suspendCancellableCoroutine { cont ->
        val c: Call = http.newCall(req)
        cont.invokeOnCancellation { c.cancel() }
        c.enqueue(object : okhttp3.Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (_readiness.value == Readiness.Ready && e is java.net.ConnectException) _readiness.value = Readiness.Down
                if (cont.isActive) cont.resume(null)
            }

            override fun onResponse(call: Call, response: Response) {
                val body = try {
                    response.use { r -> if (r.isSuccessful) r.body?.string() ?: "" else null }
                } catch (t: Throwable) {
                    null
                }
                if (cont.isActive) cont.resume(body)
            }
        })
    }

    private fun String.asObject(): JSONObject? = try {
        if (isBlank() || this == "null") JSONObject() else JSONObject(this)
    } catch (t: Throwable) {
        null
    }

    private fun String.asArray(): JSONArray? = try {
        JSONArray(this)
    } catch (t: Throwable) {
        null
    }

    /**
     * Waits until `/api/health` answers (backoff 250 ms → 2 s), up to [timeoutMs]. Concurrent callers share one
     * probe loop. Returns true when ready.
     */
    suspend fun awaitReady(timeoutMs: Long = 45_000): Boolean {
        if (_readiness.value == Readiness.Ready) return true
        return readyMutex.withLock {
            if (_readiness.value == Readiness.Ready) return@withLock true
            if (_readiness.value != Readiness.Down) _readiness.value = Readiness.Starting
            val deadline = SystemClock.elapsedRealtime() + timeoutMs
            var wait = 250L
            while (SystemClock.elapsedRealtime() < deadline) {
                val h = get("/api/health", 2_500)
                if (h != null && h.optBoolean("ok", false)) {
                    _version.value = h.optString("version", "")
                    _readiness.value = Readiness.Ready
                    return@withLock true
                }
                delay(wait)
                wait = (wait * 2).coerceAtMost(2_000)
            }
            _readiness.value = Readiness.Down
            false
        }
    }

    /** One quick probe (Settings → Test connection, the Engine screen). */
    suspend fun probe(timeoutMs: Long = 3_000): Boolean {
        val h = get("/api/health", timeoutMs)
        val up = h != null && h.optBoolean("ok", false)
        if (up) {
            _version.value = h!!.optString("version", "")
            _readiness.value = Readiness.Ready
        } else if (_readiness.value == Readiness.Ready) {
            _readiness.value = Readiness.Down
        }
        return up
    }

    fun markDown() {
        _readiness.value = Readiness.Down
    }

    // ------------------------------------------------------------------------------------- WebSocket

    /** A visible screen needs live state/frames. Must be balanced by [releaseSocket]. */
    fun acquireSocket() = synchronized(socketLock) {
        socketHolders++
        if (socketHolders == 1) {
            backoffMs = 500L
            openSocketLocked()
        }
    }

    fun releaseSocket() = synchronized(socketLock) {
        socketHolders = (socketHolders - 1).coerceAtLeast(0)
        if (socketHolders == 0) {
            reconnectJob?.cancel()
            reconnectJob = null
            socket?.close(1000, "ui hidden")
            socket = null
            _socketUp.value = false
        }
    }

    private fun openSocketLocked() {
        if (socket != null) return
        val wsUrl = baseUrl.replaceFirst("http", "ws") + "/ws"
        val req = try {
            Request.Builder().url(wsUrl).build()
        } catch (t: Throwable) {
            return
        }
        socket = http.newWebSocket(req, Listener())
    }

    private fun scheduleReconnect(failed: WebSocket) = synchronized(socketLock) {
        if (socket !== failed) return@synchronized
        socket = null
        _socketUp.value = false
        if (socketHolders == 0) return@synchronized
        reconnectJob?.cancel()
        val wait = backoffMs
        backoffMs = (backoffMs * 2).coerceAtMost(8_000)
        reconnectJob = scope.launch {
            delay(wait)
            synchronized(socketLock) { if (socketHolders > 0) openSocketLocked() }
        }
    }

    private inner class Listener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            backoffMs = 500L
            _socketUp.value = true
            _readiness.value = Readiness.Ready
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            // Only `state` pushes matter here; parse off the main thread (this is OkHttp's reader thread).
            if (!text.startsWith("{\"type\": \"state\"") && !text.contains("\"type\": \"state\"")) return
            try {
                val o = JSONObject(text).optJSONObject("state") ?: return
                _state.value = EngineState.parse(o)
            } catch (t: Throwable) {
                Log.w(TAG, "bad state push: $t")
            }
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            if (bytes.size < FRAME_BYTES) return
            synchronized(frame) { bytes.copyInto(0, frame, 0, FRAME_BYTES) }
            _frameSeq.value = _frameSeq.value + 1
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = scheduleReconnect(webSocket)

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = scheduleReconnect(webSocket)
    }

    /** Game input over the socket (web/src/lib/ws.ts `sendInput`); falls back to REST when the socket is down. */
    fun sendInput(app: String, key: String) {
        val msg = JSONObject().put("type", "input").put("app", app).put("key", key).toString()
        val sent = synchronized(socketLock) { socket?.send(msg) ?: false }
        if (!sent) scope.launch { post("/api/apps/$app/actions/input", JSONObject().put("key", key)) }
    }

    companion object {
        const val DEFAULT_BASE_URL = "http://127.0.0.1:8765"
        const val FRAME_BYTES = 32 * 32 * 3
        private const val TAG = "DeskDotWatch"
    }
}
