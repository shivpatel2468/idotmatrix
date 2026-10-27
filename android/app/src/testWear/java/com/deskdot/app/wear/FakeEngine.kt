package com.deskdot.app.wear

import org.json.JSONArray
import org.json.JSONObject
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.Base64
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * A stand-in DeskDot engine for JVM screenshot tests: a real HTTP server on 127.0.0.1 answering the endpoints the
 * watch UI uses with the same sample data as design/preview.html ("Claude Spark", "Playlist · 3 / 9", IDM-3F21A0,
 * lobby ABCD at 192.168.1.73). The UI talks to it through the production EngineClient, unchanged.
 * There is no /ws, so screens also exercise the REST fallback paths.
 */
private const val CRLF = "\r\n"

class FakeEngine {
    private val server = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
    val url: String get() = "http://127.0.0.1:${server.localPort}"
    @Volatile var connected = true

    init {
        Thread({
            while (!server.isClosed) {
                val sock = runCatching { server.accept() }.getOrNull() ?: break
                Thread({ serve(sock) }, "fake-engine-conn").apply { isDaemon = true }.start()
            }
        }, "fake-engine").apply { isDaemon = true }.start()
    }

    /** HTTP/1.1, one request per connection (Connection: close); bodies are read by Content-Length and ignored. */
    private fun serve(sock: Socket) = sock.use { s ->
        val input = s.getInputStream().bufferedReader(Charsets.ISO_8859_1)
        val first = input.readLine() ?: return
        var len = 0
        while (true) {
            val h = input.readLine() ?: break
            if (h.isEmpty()) break
            if (h.startsWith("Content-Length:", true)) len = h.substringAfter(':').trim().toIntOrNull() ?: 0
        }
        repeat(len) { input.read() }
        val path = first.split(' ').getOrElse(1) { "/" }.substringBefore('?')
        val bytes = body(path).toByteArray()
        val out = s.getOutputStream()
        out.write(("HTTP/1.1 200 OK" + CRLF + "Content-Type: application/json" + CRLF + "Content-Length: ${bytes.size}" + CRLF + "Connection: close" + CRLF + CRLF).toByteArray())
        out.write(bytes)
        out.flush()
    }

    private fun body(path: String): String = when {
        path == "/api/health" -> JSONObject().put("ok", true).put("version", "3.7.0").toString()
        path == "/api/state" -> state().toString()
        path == "/api/meta" -> meta().toString()
        path == "/api/frame" -> JSONObject().put("width", 32).put("height", 32).put("rgb", Base64.getEncoder().encodeToString(art())).toString()
        path == "/api/host" -> JSONObject().put("lan_ip", "192.168.1.73").put("port", 8765).toString()
        path == "/api/play/lobby" -> JSONObject().put("lobby", lobby()).put("lan_ready", true).toString()
        path == "/api/presets" -> JSONArray()
            .put(JSONObject().put("id", "my-chill").put("name", "Chill").put("builtin", false).put("items", JSONArray().put(1).put(2).put(3)))
            .put(JSONObject().put("id", "games").put("name", "Every game").put("builtin", true).put("items", JSONArray().put(1).put(2))).toString()
        path == "/api/playlist" -> JSONObject().put("enabled", true).put("items", items()).toString()
        path == "/api/handoff" -> JSONObject().put("mode", "clock").toString()
        path == "/api/theme" -> JSONObject().put("id", "ember").put("themes", JSONArray().put(JSONObject().put("id", "ember").put("name", "Ember"))).toString()
        path == "/api/tv" -> JSONObject().put("ok", true).put("code", "WXYZ").put("url", "http://192.168.1.73:8765/tv/WXYZ").put("lan_ready", true).toString()
        else -> JSONObject().put("ok", true).toString()
    }

    fun stop() = runCatching { server.close() }

    private fun items(): JSONArray {
        val apps = listOf("clock" to 30, "weather" to 45, "fireplace" to 0, "spark" to 60, "markets" to 20, "sysmon" to 20, "nowplaying" to 30, "snake" to 60, "pong" to 60)
        val a = JSONArray()
        apps.forEachIndexed { i, (id, d) ->
            a.put(JSONObject().put("id", "it$i").put("app", id).put("duration", if (d == 0) 30 else d).put("enabled", d != 0).put("settings", JSONObject()))
        }
        return a
    }

    fun state(): JSONObject = JSONObject()
        .put(
            "device",
            JSONObject().put("kind", "android").put("status", if (connected) "connected" else "connecting").put("address", "AA:BB:CC:3F:21:A0")
                .put("name", "IDM-3F21A0").put("rssi", -62).put("link_fps", 9.6).put("frames_dropped", 12)
                .put("last_seen", System.currentTimeMillis() / 1000.0).put("link_enabled", true),
        )
        .put(
            "engine",
            JSONObject().put("mode", "playlist").put("current", JSONObject().put("app", "spark"))
                .put("playlist", JSONObject().put("enabled", true).put("items", items()).put("index", 2).put("current_item", "it3"))
                .put("render_ms", 1.8).put("released", false).put("preset", JSONObject.NULL),
        )
        .put(
            "settings",
            JSONObject().put("brightness", 64).put("power", true).put("flip", false).put("transition", "push").put("units", "metric")
                .put("location", JSONObject().put("city", "Pune"))
                .put("display", JSONObject().put("max_fps", 12.0).put("night", JSONObject().put("enabled", true).put("start", "22:00").put("end", "07:00").put("brightness", 10)))
                .put("night_active", false).put("page_theme", "ember"),
        )

    private fun lobby() = JSONObject().put("code", "ABCD").put("app", "bomberman").put("url", "http://192.168.1.73:8765/p/ABCD")
        .put("max_players", 4).put("lan_ready", true)
        .put(
            "seats",
            JSONArray()
                .put(JSONObject().put("seat", 1).put("name", "Shiv").put("color", "#00c8ff").put("ready", true))
                .put(JSONObject().put("seat", 2).put("name", "Ana").put("color", "#ff3c5a").put("ready", false)),
        )

    private fun app(id: String, name: String, cat: String, desc: String = "", max: Int = 1, modes: JSONArray = JSONArray(), schema: JSONObject = JSONObject().put("properties", JSONObject())) =
        JSONObject().put("id", id).put("name", name).put("description", desc).put("icon", "x").put("category", cat).put("schema", schema)
            .put("supported", true).put("actions", JSONArray()).put("max_players", max).put("controls", JSONArray()).put("modes", modes)

    fun meta(): JSONObject {
        val apps = JSONArray()
        val clockSchema = JSONObject().put(
            "properties",
            JSONObject()
                .put("style", JSONObject().put("type", "string").put("title", "Style").put("enum", JSONArray().put("digital").put("analog")).put("enumLabels", JSONObject().put("digital", "Digital").put("analog", "Analog")).put("default", "analog"))
                .put("seconds", JSONObject().put("type", "boolean").put("title", "Seconds").put("default", true))
                .put("color", JSONObject().put("type", "string").put("format", "color").put("title", "Colour").put("default", "#ff4818")),
        )
        apps.put(app("clock", "Clock", "time", "A big clock with seconds, date and 6 styles.", schema = clockSchema))
        listOf("Alarm", "Countdown", "Stopwatch", "World clock", "Calendar").forEach { apps.put(app(it.lowercase(), it, "time")) }
        listOf("Weather", "Markets", "System monitor", "News", "Crypto").forEach { apps.put(app(it.lowercase().replace(' ', '_'), it, "data")) }
        listOf("Now playing", "Gallery", "Fireplace").forEach { apps.put(app(it.lowercase().replace(' ', '_'), it, "media")) }
        apps.put(app("spark", "Claude Spark", "creative"))
        listOf("Canvas", "Text").forEach { apps.put(app(it.lowercase(), it, "creative")) }
        listOf("Aurora", "Rain").forEach { apps.put(app(it.lowercase(), it, "ambient")) }
        listOf("Pomodoro", "Agent").forEach { apps.put(app(it.lowercase(), it, "productivity")) }
        listOf("Cat", "Tamagotchi").forEach { apps.put(app(it.lowercase(), it, "pets")) }
        apps.put(app("test", "Test pattern", "device"))
        val modes = JSONArray().put(JSONObject().put("id", "classic").put("name", "Classic").put("min_players", 1).put("max_players", 4).put("teams", "ffa"))
            .put(JSONObject().put("id", "teams").put("name", "Teams").put("min_players", 2).put("max_players", 4).put("teams", "versus"))
        apps.put(app("bomberman", "Bomberman", "games", max = 4, modes = modes))
        apps.put(app("snake", "Snake", "games", max = 4))
        apps.put(app("tetris", "Tetris", "games"))
        apps.put(app("pong", "Pong", "games", max = 2))
        apps.put(app("tron", "Tron", "games", max = 4))
        apps.put(app("breakout", "Breakout", "games"))
        apps.put(app("blackjack", "Blackjack", "casino", max = 6))
        val palette = JSONObject().put("ember", "#ff4818").put("ice", "#6cc4ff").put("moss", "#8fd16a").put("gold", "#ffc24a")
            .put("violet", "#b48cff").put("pink", "#ff7ab6").put("white", "#ffffff").put("grey", "#7c828c")
            .put("red", "#ff3c5a").put("cyan", "#00c8ff").put("green", "#50ff78").put("amber", "#ffc800")
        return JSONObject().put("version", "3.7.0").put("apps", apps).put("palette", palette)
    }

    companion object {
        /** preview.html `art()`: the Claude Spark sunburst. */
        fun art(): ByteArray {
            val out = ByteArray(3072)
            for (j in 0 until 32) for (i in 0 until 32) {
                val dx = i - 15.5
                val dy = j - 15.5
                val r = hypot(dx, dy)
                val a = atan2(dy, dx)
                val seg = PI / 6
                val ray = abs(((a / seg) % 1 + 1.5) % 1 - 0.5) * seg * r
                if (r < 3.6 || (r < 13.8 && ray < 1.05 && r > 1)) {
                    val t = min(1.0, r / 13.8)
                    fun mix(x: Int, y: Int) = (x + (y - x) * t).roundToInt()
                    val k = (j * 32 + i) * 3
                    out[k] = mix(255, 217).toByte(); out[k + 1] = mix(190, 72).toByte(); out[k + 2] = mix(150, 24).toByte()
                }
            }
            return out
        }
    }
}
