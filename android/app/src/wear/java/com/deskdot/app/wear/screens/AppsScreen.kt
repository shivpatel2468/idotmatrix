package com.deskdot.app.wear.screens

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.navigation.NavHostController
import androidx.wear.compose.material.Chip
import androidx.wear.compose.material.ListHeader
import androidx.wear.compose.material.Text
import com.deskdot.app.wear.Routes
import com.deskdot.app.wear.net.EngineClient
import com.deskdot.app.wear.ui.ScrollScaffold
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/**
 * DESIGN_SPEC §5.4 Apps (page 1): the picker for all apps, backed by `GET /api/meta`. Simplified from the full
 * spec: categories are flattened into one scrolling list with the app's category shown as a subtitle instead of
 * a drill-down category row + a separate "A-Z" list, and there is no on-watch search / favourites / alphabet
 * scrub yet (RemoteInput and DataStore favourites are not wired up in this pass — see the final report).
 */
@Composable
fun AppsScreen(engine: EngineClient, nav: NavHostController) {
    var apps by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    LaunchedEffect(Unit) {
        val meta = engine.get("/api/meta")
        val arr: JSONArray = meta.optJSONArray("apps") ?: JSONArray()
        apps = (0 until arr.length()).map { arr.getJSONObject(it) }
            .filter { it.optString("category") != "games" }
            .sortedBy { it.optString("name") }
    }
    ScrollScaffold {
        item { ListHeader { Text("Apps") } }
        items(apps.size) { i ->
            val app = apps[i]
            val supported = app.optBoolean("supported", true)
            Chip(
                label = { Text(app.optString("name")) },
                secondaryLabel = { Text(if (supported) app.optString("category") else "Not on this watch") },
                onClick = { if (supported) nav.navigate(Routes.appDetail(app.optString("id"))) },
                enabled = supported,
            )
        }
    }
}

@Composable
fun AppDetailScreen(engine: EngineClient, id: String, nav: NavHostController) {
    var meta by remember { mutableStateOf<JSONObject?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(id) {
        val all = engine.get("/api/meta").optJSONArray("apps") ?: JSONArray()
        for (i in 0 until all.length()) {
            val a = all.getJSONObject(i)
            if (a.optString("id") == id) {
                meta = a
                break
            }
        }
    }
    ScrollScaffold {
        item { ListHeader { Text(meta?.optString("name") ?: id) } }
        item { Text(meta?.optString("description").orEmpty()) }
        item {
            Chip(
                label = { Text("Show now") },
                onClick = { scope.launch { engine.post("/api/apps/$id/activate") } },
            )
        }
        item {
            Chip(
                label = { Text("Add to playlist") },
                onClick = {
                    scope.launch {
                        val current = engine.get("/api/playlist")
                        val items = current.optJSONArray("items") ?: JSONArray()
                        items.put(JSONObject().put("app", id).put("duration", 30))
                        engine.put("/api/playlist", JSONObject(current.toString()).put("items", items))
                    }
                },
            )
        }
        val actions = meta?.optJSONArray("actions")
        if (actions != null) {
            items(actions.length()) { i ->
                val action = actions.getString(i)
                Chip(label = { Text(action) }, onClick = { scope.launch { engine.post("/api/apps/$id/actions/$action") } })
            }
        }
    }
}
