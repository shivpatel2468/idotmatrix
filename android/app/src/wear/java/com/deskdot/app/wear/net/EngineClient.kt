package com.deskdot.app.wear.net

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Talks to the DeskDot engine the same way the studio does: REST for commands, one WebSocket (`/ws`) for the
 * JSON `state` push and binary 32x32 RGB preview frames (web/src/lib/ws.ts is the reference client).
 *
 * The default base URL is `http://127.0.0.1:8765` (the engine runs in-process via Chaquopy, see EngineService).
 * Settings -> Advanced -> Engine address (DESIGN_SPEC §5.11) can point this at another host; that override is
 * read by the caller and passed into [EngineClient]'s constructor.
 */
class EngineClient(private var baseUrl: String = DEFAULT_BASE_URL) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .writeTimeout(5, TimeUnit.SECONDS)
        .build()

    private val jsonMedia = "application/json".toMediaType()

    private var socket: WebSocket? = null
    private val _state = MutableStateFlow<JSONObject?>(null)
    val state: StateFlow<JSONObject?> = _state.asStateFlow()

    private val _frame = MutableStateFlow<ByteArray?>(null)
    /** Newest 3072-byte (32x32 RGB) preview frame; null until the first one arrives. Latest frame wins — the
     * studio's own rule (CLAUDE.md #6) applies to the client side too: never buffer a backlog of frames. */
    val frame: StateFlow<ByteArray?> = _frame.asStateFlow()

    private val _connected = MutableStateFlow(false)
    val wsConnected: StateFlow<Boolean> = _connected.asStateFlow()

    fun setBaseUrl(url: String) {
        baseUrl = url.trimEnd('/')
    }

    // ---------------------------------------------------------------- REST
    //
    // Every call below swallows network failures (timeouts, ECONNREFUSED while the Chaquopy engine thread is
    // still booting, DNS errors after an Advanced > Engine address typo, …) and degrades to an empty
    // JSONObject/JSONArray rather than throwing. This was NOT optional: an unhandled ConnectException thrown
    // from a `LaunchedEffect` coroutine crashes the whole Activity (confirmed live on a Fossil Gen 6 — the
    // onboarding scan call raced the engine's own startup and took the app down with
    // "FATAL EXCEPTION: main ... java.net.ConnectException: Failed to connect to /127.0.0.1:8765"). Screens
    // read "empty" as "try again" / "nothing yet", which is always a safe interpretation here.
    suspend fun get(path: String): JSONObject = withContext(Dispatchers.IO) {
        runCatching {
            http.newCall(Request.Builder().url(baseUrl + path).get().build()).execute().use { resp ->
                parseObjectOrEmpty(resp.body?.string())
            }
        }.getOrElse { JSONObject() }
    }

    suspend fun getArray(path: String): org.json.JSONArray = withContext(Dispatchers.IO) {
        runCatching {
            http.newCall(Request.Builder().url(baseUrl + path).get().build()).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                runCatching { org.json.JSONArray(body) }.getOrElse { org.json.JSONArray() }
            }
        }.getOrElse { org.json.JSONArray() }
    }

    suspend fun post(path: String, body: JSONObject = JSONObject()): JSONObject = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url(baseUrl + path).post(body.toString().toRequestBody(jsonMedia)).build()
            http.newCall(req).execute().use { resp -> parseObjectOrEmpty(resp.body?.string()) }
        }.getOrElse { JSONObject() }
    }

    suspend fun put(path: String, body: JSONObject = JSONObject()): JSONObject = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url(baseUrl + path).put(body.toString().toRequestBody(jsonMedia)).build()
            http.newCall(req).execute().use { resp -> parseObjectOrEmpty(resp.body?.string()) }
        }.getOrElse { JSONObject() }
    }

    suspend fun patch(path: String, body: JSONObject = JSONObject()): JSONObject = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url(baseUrl + path).patch(body.toString().toRequestBody(jsonMedia)).build()
            http.newCall(req).execute().use { resp -> parseObjectOrEmpty(resp.body?.string()) }
        }.getOrElse { JSONObject() }
    }

    suspend fun delete(path: String): JSONObject = withContext(Dispatchers.IO) {
        runCatching {
            http.newCall(Request.Builder().url(baseUrl + path).delete().build()).execute().use { resp ->
                parseObjectOrEmpty(resp.body?.string())
            }
        }.getOrElse { JSONObject() }
    }

    private fun parseObjectOrEmpty(body: String?): JSONObject =
        runCatching { JSONObject(body ?: "{}") }.getOrElse { JSONObject() }

    // ----------------------------------------------------------- WebSocket
    /** Opens `/ws`. Call only while the UI is visible (perf budget: "the WebSocket disconnects when the UI
     * isn't visible") — the caller (the Now Playing / Lobby / Tile screens) owns the lifecycle via
     * connect()/disconnect() from onStart/onStop. */
    fun connect(scope: CoroutineScope) {
        if (socket != null) return
        val wsUrl = baseUrl.replaceFirst("http", "ws") + "/ws"
        val req = Request.Builder().url(wsUrl).build()
        socket = http.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) {
                _connected.value = true
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                scope.launch {
                    val msg = runCatching { JSONObject(text) }.getOrNull() ?: return@launch
                    if (msg.optString("type") == "state") _state.value = msg.optJSONObject("state")
                }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                // latest frame wins: never queue (CLAUDE.md #6)
                _frame.value = bytes.toByteArray()
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                _connected.value = false
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: okhttp3.Response?) {
                _connected.value = false
            }
        })
    }

    fun disconnect() {
        socket?.close(1000, "ui hidden")
        socket = null
        _connected.value = false
    }

    /** Gamepad / game input over the socket, same shape as web/src/lib/ws.ts `sendInput`. */
    fun sendInput(app: String, key: String, player: Int = 1) {
        val msg = JSONObject().put("type", "input").put("app", app).put("key", key)
        if (player > 1) msg.put("player", player)
        socket?.send(msg.toString())
    }

    companion object {
        const val DEFAULT_BASE_URL = "http://127.0.0.1:8765"
    }
}
