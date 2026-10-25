package com.deskdot.app.wear.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ListHeader
import androidx.wear.compose.material.Text
import com.deskdot.app.wear.Routes
import com.deskdot.app.wear.net.EngineClient
import com.deskdot.app.wear.ui.QrPlate
import com.deskdot.app.wear.ui.ScrollScaffold
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/** DESIGN_SPEC §5.5.1: games list, plus Casino and TV-link rows. */
@Composable
fun GamesScreen(engine: EngineClient, nav: NavHostController) {
    var games by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    LaunchedEffect(Unit) {
        val arr = engine.get("/api/meta").optJSONArray("apps") ?: JSONArray()
        games = (0 until arr.length()).map { arr.getJSONObject(it) }.filter { it.optString("category") == "games" }
    }
    val scope = rememberCoroutineScope()
    ScrollScaffold {
        item { ListHeader { Text("Games") } }
        items(games.size) { i ->
            val g = games[i]
            Chip(
                label = { Text(g.optString("name")) },
                secondaryLabel = { Text(if (g.optInt("max_players", 1) > 1) "1-${g.optInt("max_players")} players" else "Solo") },
                onClick = { nav.navigate(Routes.gameSetup(g.optString("id"))) },
            )
        }
        item { Chip(label = { Text("Casino") }, onClick = { nav.navigate(Routes.gameSetup("casino_holdem")) }) }
        item {
            Chip(
                label = { Text("TV link") },
                onClick = { scope.launch { engine.post("/api/tv"); nav.navigate(Routes.lobby("tv")) } },
            )
        }
    }
}

/** DESIGN_SPEC §5.5.2: mode / players / Solo-Host-AI for one game. */
@Composable
fun GameSetupScreen(engine: EngineClient, id: String, nav: NavHostController) {
    var players by remember { mutableStateOf(2) }
    var aiOn by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    ScrollScaffold {
        item { ListHeader { Text(id) } }
        item {
            Chip(
                label = { Text("Players: $players") },
                onClick = { players = if (players >= 4) 2 else players + 1 },
            )
        }
        item {
            Chip(
                label = { Text(if (aiOn) "Let AI play: On" else "Let AI play: Off") },
                onClick = { aiOn = !aiOn },
            )
        }
        item {
            Chip(
                label = { Text("Solo") },
                onClick = {
                    scope.launch {
                        val settings = JSONObject().put("players", players).put("ai", aiOn)
                        engine.post("/api/apps/$id/activate", JSONObject().put("settings", settings))
                        nav.navigate(Routes.gamepad(id))
                    }
                },
            )
        }
        item {
            Chip(
                label = { Text("Host") },
                onClick = {
                    scope.launch {
                        engine.post("/api/play/lobby", JSONObject().put("app", id))
                        nav.navigate(Routes.lobby(id))
                    }
                },
            )
        }
    }
}

/**
 * DESIGN_SPEC §5.5.3: a 2-page VerticalPager — page Q (join QR, full brightness, no TimeText/fade) and page P
 * (players list + Start/QR/End). Brightness/FLAG_KEEP_SCREEN_ON while page Q is visible is left to the hosting
 * Activity (see MainActivity) rather than duplicated here.
 */
@Composable
fun LobbyScreen(engine: EngineClient, app: String, nav: NavHostController) {
    var lobbyUrl by remember { mutableStateOf<String?>(null) }
    var roomCode by remember { mutableStateOf("") }
    var players by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    val scope = rememberCoroutineScope()

    suspend fun refresh() {
        val lobby = engine.get("/api/play/lobby")
        lobbyUrl = lobby.optString("url").ifEmpty { null }
        roomCode = lobby.optString("code")
        val seats = lobby.optJSONArray("players") ?: JSONArray()
        players = (0 until seats.length()).map { seats.getJSONObject(it) }
    }

    LaunchedEffect(Unit) { refresh() }
    DisposableEffect(Unit) {
        val job = scope.launch {
            while (true) {
                refresh()
                kotlinx.coroutines.delay(2000)
            }
        }
        onDispose { job.cancel() }
    }

    val pagerState = rememberPagerState(initialPage = 0) { 2 }
    VerticalPager(state = pagerState, modifier = Modifier.fillMaxSize()) { page ->
        if (page == 0) {
            // Page Q: join QR. Fixed layout, no TimeText / fade mask (§5.5.3).
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(lobbyUrl?.removePrefix("http://")?.substringBefore("/p/") ?: "...")
                    QrPlate(content = lobbyUrl ?: "", plateSizeDp = 130)
                    Text("/p/$roomCode")
                }
            }
        } else {
            // Page P: players + action row.
            ScrollScaffold(showTimeText = false) {
                item { ListHeader { Text("Players ${players.size} - room $roomCode") } }
                items(players.size) { i ->
                    val p = players[i]
                    Chip(label = { Text(p.optString("name", "Open seat")) }, onClick = {})
                }
                item {
                    Chip(label = { Text("Start") }, onClick = { scope.launch { engine.post("/api/play/lobby/start") } })
                }
                item {
                    Chip(
                        label = { Text("End") },
                        onClick = {
                            scope.launch {
                                engine.delete("/api/play/lobby")
                                nav.popBackStack()
                            }
                        },
                    )
                }
            }
        }
    }
}

/** DESIGN_SPEC §5.5.5: the watch as a solo-play controller. Fixed layout, no TimeText. */
@Composable
fun GamepadScreen(engine: EngineClient, id: String) {
    val scope = rememberCoroutineScope()
    fun send(key: String) = scope.launch { engine.sendInput(id, key) }
    DisposableEffect(Unit) {
        engine.connect(scope)
        onDispose { engine.disconnect() }
    }
    Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
        Chip(label = { Text("Up") }, onClick = { send("up") }, modifier = Modifier.padding(top = 24.dp))
        Chip(label = { Text("Left") }, onClick = { send("left") })
        Chip(label = { Text("A") }, onClick = { send("a") })
        Chip(label = { Text("B") }, onClick = { send("b") })
        Chip(label = { Text("Right") }, onClick = { send("right") })
        Chip(label = { Text("Down") }, onClick = { send("down") })
    }
}
