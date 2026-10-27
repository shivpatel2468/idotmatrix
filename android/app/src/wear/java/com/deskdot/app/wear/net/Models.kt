package com.deskdot.app.wear.net

import androidx.compose.runtime.Immutable
import org.json.JSONArray
import org.json.JSONObject

/*
 * Typed, immutable views of the engine's JSON (src/deskdot/server.py, engine/runtime.py `snapshot()`), parsed once
 * per push off the main thread. Only the fields the watch shows are kept, so a state push costs one small object.
 */

@Immutable
data class DeviceInfo(
    val status: String = "disconnected",
    val address: String? = null,
    val name: String? = null,
    val rssi: Int? = null,
    val linkFps: Double = 0.0,
    val framesDropped: Int = 0,
    val lastSeen: Double? = null,
    val linkEnabled: Boolean = true,
    val hint: String? = null,
    val attempts: Int = 0,
) {
    val connected get() = status == "connected"
    val connecting get() = status == "connecting" || status == "scanning"

    companion object {
        fun parse(o: JSONObject?): DeviceInfo {
            if (o == null) return DeviceInfo()
            return DeviceInfo(
                status = o.optString("status", "disconnected"),
                address = o.optStringOrNull("address"),
                name = o.optStringOrNull("name"),
                rssi = if (o.isNull("rssi")) null else o.optInt("rssi"),
                linkFps = o.optDouble("link_fps", 0.0).finiteOr(0.0),
                framesDropped = o.optInt("frames_dropped", 0),
                lastSeen = if (o.isNull("last_seen")) null else o.optDouble("last_seen").takeIf { it.isFinite() },
                linkEnabled = o.optBoolean("link_enabled", true),
                hint = o.optStringOrNull("hint"),
                attempts = o.optInt("attempts", 0),
            )
        }
    }
}

@Immutable
data class PlItem(val id: String, val app: String, val duration: Double, val enabled: Boolean, val settings: JSONObject?) {
    fun toJson(): JSONObject = JSONObject().put("id", id).put("app", app).put("duration", duration).put("enabled", enabled)
        .also { if (settings != null) it.put("settings", settings) }

    companion object {
        fun parse(o: JSONObject) = PlItem(
            id = o.optString("id"),
            app = o.optString("app"),
            duration = o.optDouble("duration", 15.0).finiteOr(15.0),
            enabled = o.optBoolean("enabled", true),
            settings = o.optJSONObject("settings")?.takeIf { it.length() > 0 },
        )
    }
}

@Immutable
data class Night(val enabled: Boolean = false, val start: String = "23:00", val end: String = "07:00", val brightness: Int = 10)

@Immutable
data class EngineState(
    val device: DeviceInfo = DeviceInfo(),
    val mode: String = "",
    val currentApp: String? = null,
    val playlistEnabled: Boolean = false,
    val items: List<PlItem> = emptyList(),
    val plIndex: Int = 0,
    val currentItem: String? = null,
    val presetName: String? = null,
    val presetShuffle: Boolean = false,
    val brightness: Int = 60,
    val power: Boolean = true,
    val flip: Boolean = false,
    val transition: String = "push",
    val maxFps: Double = 12.0,
    val night: Night = Night(),
    val nightActive: Boolean = false,
    val renderMs: Double = 0.0,
    val released: Boolean = false,
    val pageTheme: String = "",
    val units: String = "metric",
    val city: String = "",
) {
    /** The playlist is the active source and running. */
    val playing get() = mode == "playlist" && playlistEnabled

    companion object {
        fun parse(o: JSONObject): EngineState {
            val e = o.optJSONObject("engine") ?: JSONObject()
            val cur = e.optJSONObject("current")
            val pl = e.optJSONObject("playlist") ?: JSONObject()
            val s = o.optJSONObject("settings") ?: JSONObject()
            val d = s.optJSONObject("display") ?: JSONObject()
            val n = d.optJSONObject("night") ?: JSONObject()
            val preset = e.optJSONObject("preset")
            val items = pl.optJSONArray("items").objects().map { PlItem.parse(it) }
            return EngineState(
                device = DeviceInfo.parse(o.optJSONObject("device")),
                mode = e.optString("mode", ""),
                currentApp = cur?.optStringOrNull("app"),
                playlistEnabled = pl.optBoolean("enabled", false),
                items = items,
                plIndex = pl.optInt("index", 0),
                currentItem = pl.optStringOrNull("current_item"),
                presetName = preset?.optStringOrNull("name"),
                presetShuffle = preset?.optBoolean("shuffle", false) ?: false,
                brightness = s.optInt("brightness", 60),
                power = s.optBoolean("power", true),
                flip = s.optBoolean("flip", false),
                transition = s.optString("transition", "push"),
                maxFps = d.optDouble("max_fps", 12.0).finiteOr(12.0),
                night = Night(
                    enabled = n.optBoolean("enabled", false),
                    start = n.optString("start", "23:00"),
                    end = n.optString("end", "07:00"),
                    brightness = n.optInt("brightness", 10),
                ),
                nightActive = s.optBoolean("night_active", false),
                renderMs = e.optDouble("render_ms", 0.0).finiteOr(0.0),
                released = e.optBoolean("released", false),
                pageTheme = s.optString("page_theme", ""),
                units = s.optString("units", "metric"),
                city = s.optJSONObject("location")?.optString("city", "").orEmpty(),
            )
        }
    }
}

@Immutable
data class GameMode(val id: String, val name: String, val minPlayers: Int, val maxPlayers: Int)

@Immutable
data class AppAction(val id: String, val label: String)

/** One entry of `GET /api/meta` `apps[]`. [schema] stays raw JSON: only the detail screen reads it. */
@Immutable
data class AppMeta(
    val id: String,
    val name: String,
    val description: String,
    val category: String,
    val supported: Boolean,
    val maxPlayers: Int,
    val modes: List<GameMode>,
    val actions: List<AppAction>,
    val schema: JSONObject?,
) {
    val isGame get() = category == "games"
    val isCasino get() = category == "casino"

    companion object {
        fun parse(o: JSONObject) = AppMeta(
            id = o.optString("id"),
            name = o.optString("name", o.optString("id")),
            description = o.optString("description", ""),
            category = o.optString("category", ""),
            supported = o.optBoolean("supported", true),
            maxPlayers = o.optInt("max_players", 1),
            modes = o.optJSONArray("modes").objects().map {
                GameMode(it.optString("id"), it.optString("name"), it.optInt("min_players", 1), it.optInt("max_players", 1))
            },
            actions = o.optJSONArray("actions").objects().map { AppAction(it.optString("id"), it.optString("label")) },
            schema = o.optJSONObject("schema"),
        )
    }
}

@Immutable
data class Meta(val version: String, val apps: List<AppMeta>, val palette: List<Pair<String, String>>) {
    private val byId: Map<String, AppMeta> = apps.associateBy { it.id }
    fun app(id: String?): AppMeta? = id?.let { byId[it] }
    fun name(id: String?): String = app(id)?.name ?: id.orEmpty()

    companion object {
        fun parse(o: JSONObject): Meta {
            val pal = o.optJSONObject("palette")
            val palette = buildList { pal?.keys()?.forEach { k -> add(k to pal.optString(k)) } }
            return Meta(o.optString("version", ""), o.optJSONArray("apps").objects().map { AppMeta.parse(it) }, palette)
        }
    }
}

@Immutable
data class Seat(val seat: Int, val name: String, val color: String, val ready: Boolean)

@Immutable
data class Lobby(
    val code: String,
    val app: String,
    val url: String?,
    val maxPlayers: Int,
    val lanReady: Boolean,
    val seats: List<Seat>,
) {
    companion object {
        fun parse(o: JSONObject?): Lobby? {
            if (o == null || !o.has("code")) return null
            return Lobby(
                code = o.optString("code"),
                app = o.optString("app"),
                url = o.optStringOrNull("url"),
                maxPlayers = o.optInt("max_players", 4),
                lanReady = o.optBoolean("lan_ready", true),
                seats = o.optJSONArray("seats").objects().map {
                    Seat(it.optInt("seat"), it.optString("name"), it.optString("color", "#00c8ff"), it.optBoolean("ready"))
                },
            )
        }
    }
}

@Immutable
data class Preset(val id: String, val name: String, val builtin: Boolean, val count: Int) {
    companion object {
        fun parse(o: JSONObject) = Preset(
            o.optString("id"), o.optString("name"), o.optBoolean("builtin", true), o.optJSONArray("items")?.length() ?: 0,
        )
    }
}

@Immutable
data class HostInfo(val lanIp: String, val port: Int) {
    /** A usable LAN address (not loopback / unset). */
    val onLan get() = lanIp.isNotEmpty() && !lanIp.startsWith("127.") && lanIp != "0.0.0.0"
}

@Immutable
data class TvLink(val code: String, val url: String, val lanReady: Boolean, val look: String?) {
    companion object {
        fun parse(o: JSONObject?): TvLink? {
            if (o == null || !o.has("code")) return null
            return TvLink(o.optString("code"), o.optString("url"), o.optBoolean("lan_ready", true), o.optJSONObject("display")?.optStringOrNull("look"))
        }
    }
}

// ---------------------------------------------------------------------------------------------- helpers

internal fun JSONObject.optStringOrNull(key: String): String? =
    if (!has(key) || isNull(key)) null else optString(key).takeIf { it.isNotEmpty() }

internal fun JSONArray?.objects(): List<JSONObject> {
    if (this == null) return emptyList()
    val out = ArrayList<JSONObject>(length())
    for (i in 0 until length()) optJSONObject(i)?.let { out.add(it) }
    return out
}

private fun Double.finiteOr(d: Double) = if (isFinite()) this else d
