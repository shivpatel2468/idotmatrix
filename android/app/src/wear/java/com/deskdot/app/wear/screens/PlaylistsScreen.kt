package com.deskdot.app.wear.screens

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ListHeader
import androidx.wear.compose.material.Text
import com.deskdot.app.wear.net.EngineClient
import com.deskdot.app.wear.ui.ScrollScaffold
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/** DESIGN_SPEC §5.6: transport row, current items, presets. */
@Composable
fun PlaylistsScreen(engine: EngineClient) {
    var playlist by remember { mutableStateOf<JSONObject?>(null) }
    var presets by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        playlist = engine.get("/api/playlist")
        val arr = engine.getArray("/api/presets")
        presets = (0 until arr.length()).map { arr.getJSONObject(it) }
    }

    ScrollScaffold {
        item { ListHeader { Text("Playlist") } }
        item { Chip(label = { Text("Prev") }, onClick = { scope.launch { engine.post("/api/playlist/prev") } }) }
        item { Chip(label = { Text("Play / Stop") }, onClick = { scope.launch { engine.post("/api/playlist/play") } }) }
        item { Chip(label = { Text("Next") }, onClick = { scope.launch { engine.post("/api/playlist/next") } }) }
        val items = playlist?.optJSONArray("items")
        if (items != null) {
            items(items.length()) { i ->
                val it = items.getJSONObject(i)
                Chip(label = { Text(it.optString("app")) }, secondaryLabel = { Text("${it.optInt("duration")}s") }, onClick = {})
            }
        }
        item { ListHeader { Text("Presets") } }
        items(presets.size) { i ->
            val p = presets[i]
            Chip(
                label = { Text(p.optString("name")) },
                onClick = { scope.launch { engine.post("/api/presets/${p.optString("id")}/play") } },
            )
        }
    }
}
