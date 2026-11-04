package com.deskdot.app

import com.google.android.gms.tasks.Task
import com.google.android.gms.tasks.TaskCompletionSource
import com.google.android.gms.wearable.WearableListenerService
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * The phone half of the watch app (android/wear/SPEC.md): the watch asks over Google's Wearable Data
 * Layer and this answers by calling the engine running on this phone (127.0.0.1:8765), so the watch never
 * talks to the panel or the network itself (I-WEAR-2).
 *
 * Only these requests exist, by construction — the watch can't reach raw device, calibration or settings
 * endpoints:
 *  - /deskdot/summary    → {connected, status, current, name, brightness, preset, theme}
 *  - /deskdot/apps       → [{id, name, category}] (apps this phone can show)
 *  - /deskdot/presets    → [{id, name}]
 *  - /deskdot/frame      → PNG of exactly what the panel shows (128 × 128)
 *  - /deskdot/activate   ← {"id": app}       show an app now
 *  - /deskdot/preset     ← {"id": preset}    play a preset
 *  - /deskdot/brightness ← {"value": 5..100}
 * Errors come back as {"error": "engine" | "bad request" | ...}; nothing here polls or holds a wake lock:
 * the system starts the service for a request and stops it after.
 */
class WearBridgeService : WearableListenerService() {
    private val pool = Executors.newSingleThreadExecutor()
    private val http = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(4, TimeUnit.SECONDS)
        .build()

    override fun onRequest(nodeId: String, path: String, request: ByteArray): Task<ByteArray> {
        val done = TaskCompletionSource<ByteArray>()
        pool.execute {
            val reply = runCatching { handle(path, request) }.getOrElse { e ->
                JSONObject().put("error", if (e is java.net.ConnectException) "engine" else (e.message ?: "error")).toString().toByteArray()
            }
            done.setResult(reply)
        }
        return done.task
    }

    override fun onDestroy() {
        pool.shutdown()
        super.onDestroy()
    }

    private fun handle(path: String, request: ByteArray): ByteArray = when (path) {
        SUMMARY -> summary().toString().toByteArray()
        APPS -> apps().toString().toByteArray()
        PRESETS -> presets().toString().toByteArray()
        FRAME -> bytes("/api/frame.png?scale=4")
        ACTIVATE -> {
            val id = idFrom(request)
            send("POST", "/api/apps/$id/activate", "{}")
            ok()
        }
        PRESET -> {
            val id = idFrom(request)
            send("POST", "/api/presets/$id/play", "{}")
            ok()
        }
        BRIGHTNESS -> {
            val v = JSONObject(String(request)).getInt("value").coerceIn(5, 100)
            send("PATCH", "/api/settings", JSONObject().put("brightness", v).toString())
            ok()
        }
        else -> JSONObject().put("error", "unknown request").toString().toByteArray()
    }

    private fun summary(): JSONObject {
        val state = JSONObject(text("/api/state"))
        val engine = state.optJSONObject("engine") ?: JSONObject()
        val device = state.optJSONObject("device") ?: JSONObject()
        val settings = state.optJSONObject("settings") ?: JSONObject()
        val current = engine.optString("current", "")
        val theme = runCatching { JSONObject(text("/api/theme")).optString("id", "") }.getOrDefault("")
        return JSONObject()
            .put("connected", device.optString("status") == "connected")
            .put("status", device.optString("status", ""))
            .put("current", current)
            .put("name", names()[current] ?: current)
            .put("brightness", settings.optInt("brightness", 0))
            .put("preset", engine.optString("active_preset", ""))
            .put("theme", theme)
    }

    private fun apps(): JSONArray {
        val meta = JSONObject(text("/api/meta")).optJSONArray("apps") ?: JSONArray()
        val out = JSONArray()
        for (i in 0 until meta.length()) {
            val a = meta.getJSONObject(i)
            if (!a.optBoolean("supported", true)) continue
            out.put(JSONObject().put("id", a.optString("id")).put("name", a.optString("name")).put("category", a.optString("category")))
        }
        return out
    }

    private fun presets(): JSONArray {
        val list = JSONArray(text("/api/presets"))
        val out = JSONArray()
        for (i in 0 until list.length()) {
            val p = list.getJSONObject(i)
            out.put(JSONObject().put("id", p.optString("id")).put("name", p.optString("name")))
        }
        return out
    }

    /** App names, fetched once (the app list doesn't change while the engine runs). */
    private fun names(): Map<String, String> {
        cachedNames?.let { return it }
        val m = HashMap<String, String>()
        val a = apps()
        for (i in 0 until a.length()) a.getJSONObject(i).let { m[it.getString("id")] = it.getString("name") }
        cachedNames = m
        return m
    }

    private fun idFrom(request: ByteArray): String {
        val id = JSONObject(String(request)).getString("id")
        require(ID.matches(id)) { "bad request" }
        return id
    }

    private fun ok() = JSONObject().put("ok", true).toString().toByteArray()

    private fun text(path: String): String = String(bytes(path))

    private fun bytes(path: String): ByteArray =
        http.newCall(Request.Builder().url(BASE + path).build()).execute().use { r ->
            check(r.isSuccessful) { "engine ${r.code}" }
            r.body!!.bytes()
        }

    private fun send(method: String, path: String, json: String) {
        val body = json.toRequestBody("application/json".toMediaType())
        http.newCall(Request.Builder().url(BASE + path).method(method, body).build()).execute().use { r ->
            check(r.isSuccessful) { "engine ${r.code}" }
        }
    }

    companion object {
        private const val BASE = "http://127.0.0.1:${EngineService.PORT}"
        private val ID = Regex("^[a-z0-9_-]{1,64}$")
        @Volatile private var cachedNames: Map<String, String>? = null

        const val SUMMARY = "/deskdot/summary"
        const val APPS = "/deskdot/apps"
        const val PRESETS = "/deskdot/presets"
        const val FRAME = "/deskdot/frame"
        const val ACTIVATE = "/deskdot/activate"
        const val PRESET = "/deskdot/preset"
        const val BRIGHTNESS = "/deskdot/brightness"
    }
}
