package com.deskdot.wear

import android.content.Context
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.tasks.await
import org.json.JSONArray
import org.json.JSONObject

/** What the watch shows of the phone's engine (the phone's WearBridgeService builds it). */
data class Summary(
    val connected: Boolean,
    val status: String,
    val current: String,
    val name: String,
    val brightness: Int,
    val preset: String,
    val theme: String,
)

data class AppItem(val id: String, val name: String, val category: String)
data class PresetItem(val id: String, val name: String)

/**
 * The phone's summary. Phone builds up to 3.9.0 copied the engine's `current` object ({key, app, item, kind…})
 * into `current` and `name` as raw text; read the app id out of it and leave the name empty, so the watch shows the
 * app's own name from its list instead of the raw text.
 */
internal fun parseSummary(o: JSONObject): Summary {
    fun appOf(v: Any?): String = when (v) {
        is JSONObject -> if (v.isNull("app")) "" else v.optString("app")
        is String -> if (v.trimStart().startsWith("{")) runCatching { appOf(JSONObject(v)) }.getOrDefault("") else v
        else -> ""
    }
    val current = appOf(if (o.isNull("current")) null else o.opt("current"))
    val name = o.optString("name").takeUnless { it.trimStart().startsWith("{") || it == "null" } ?: ""
    return Summary(
        o.optBoolean("connected"), o.optString("status"), current, name,
        o.optInt("brightness"), o.optString("preset"), o.optString("theme"),
    )
}

/** Why the watch can't show the panel right now, in plain words. */
class PhoneUnavailable(message: String) : Exception(message)

/**
 * The watch's only line out: request/response messages to the phone app over Google's Wearable Data Layer
 * (paths under /deskdot, answered by the phone's WearBridgeService). No network, no polling of its own:
 * the screen asks while it's visible, and nothing runs when it isn't.
 */
class PhoneLink(context: Context) {
    private val messages = Wearable.getMessageClient(context)
    private val nodes = Wearable.getNodeClient(context)
    @Volatile private var phone: String? = null

    private suspend fun ask(path: String, body: ByteArray = ByteArray(0)): ByteArray {
        val id = phone ?: nodes.connectedNodes.await().let { list -> (list.firstOrNull { it.isNearby } ?: list.firstOrNull())?.id }
            ?: throw PhoneUnavailable("Your phone isn't connected.")
        phone = id
        return try {
            messages.sendRequest(id, path, body).await()
        } catch (e: Exception) {
            phone = null
            throw PhoneUnavailable("Open DeskDot on your phone.")
        }
    }

    private fun check(json: String): String {
        if (json.startsWith("{")) {
            val o = JSONObject(json)
            if (o.has("error")) throw PhoneUnavailable(if (o.getString("error") == "engine") "Open DeskDot on your phone." else o.getString("error"))
        }
        return json
    }

    suspend fun summary(): Summary {
        val o = JSONObject(check(String(ask(SUMMARY))))
        return parseSummary(o)
    }

    suspend fun apps(): List<AppItem> {
        val a = JSONArray(check(String(ask(APPS))))
        return List(a.length()) { i -> a.getJSONObject(i).let { AppItem(it.optString("id"), it.optString("name"), it.optString("category")) } }
    }

    suspend fun presets(): List<PresetItem> {
        val a = JSONArray(check(String(ask(PRESETS))))
        return List(a.length()) { i -> a.getJSONObject(i).let { PresetItem(it.optString("id"), it.optString("name")) } }
    }

    /** PNG of what the panel shows (empty when the phone couldn't get it). */
    suspend fun frame(): ByteArray = ask(FRAME)

    suspend fun activate(id: String) = check(String(ask(ACTIVATE, JSONObject().put("id", id).toString().toByteArray())))
    suspend fun playPreset(id: String) = check(String(ask(PRESET, JSONObject().put("id", id).toString().toByteArray())))
    suspend fun brightness(value: Int) = check(String(ask(BRIGHTNESS, JSONObject().put("value", value).toString().toByteArray())))

    companion object {
        const val SUMMARY = "/deskdot/summary"
        const val APPS = "/deskdot/apps"
        const val PRESETS = "/deskdot/presets"
        const val FRAME = "/deskdot/frame"
        const val ACTIVATE = "/deskdot/activate"
        const val PRESET = "/deskdot/preset"
        const val BRIGHTNESS = "/deskdot/brightness"
    }
}
