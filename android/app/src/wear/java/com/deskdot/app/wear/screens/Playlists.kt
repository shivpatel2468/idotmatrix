package com.deskdot.app.wear.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.PagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.geometry.Offset
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.navigation.NavHostController
import com.deskdot.app.wear.design.CaptionItem
import com.deskdot.app.wear.design.DrawnItem
import com.deskdot.app.wear.design.HeaderItem
import com.deskdot.app.wear.design.Icons
import com.deskdot.app.wear.design.LocalHaptics
import com.deskdot.app.wear.design.LocalLook
import com.deskdot.app.wear.design.Neutral
import com.deskdot.app.wear.design.OFont
import com.deskdot.app.wear.design.SettingItem
import com.deskdot.app.wear.design.SuiteList
import com.deskdot.app.wear.design.TAlign
import com.deskdot.app.wear.design.TS
import com.deskdot.app.wear.design.TStyle
import com.deskdot.app.wear.design.Trailing
import com.deskdot.app.wear.design.drawRun
import com.deskdot.app.wear.design.rememberSuiteListState
import com.deskdot.app.wear.design.rowPress
import com.deskdot.app.wear.design.textRun
import com.deskdot.app.wear.nav.NumberReq
import com.deskdot.app.wear.nav.Route
import com.deskdot.app.wear.nav.plItem
import com.deskdot.app.wear.net.EngineClient
import com.deskdot.app.wear.net.EngineState
import com.deskdot.app.wear.net.PlItem
import com.deskdot.app.wear.net.Preset
import com.deskdot.app.wear.net.objects
import com.deskdot.app.wear.nav.Pick
import com.deskdot.app.wear.ui.Act
import com.deskdot.app.wear.ui.ActionRowItem
import com.deskdot.app.wear.ui.Btn
import com.deskdot.app.wear.ui.FocusWhenActive
import com.deskdot.app.wear.ui.GlassPillItem
import com.deskdot.app.wear.ui.LabelMode
import com.deskdot.app.wear.ui.LetterRowItem
import com.deskdot.app.wear.ui.LocalDd
import com.deskdot.app.wear.ui.LocalToast
import com.deskdot.app.wear.ui.Screen
import com.deskdot.app.wear.ui.StatusLineItem
import com.deskdot.app.wear.ui.checkCircle
import com.deskdot.app.wear.ui.rememberConfirm
import com.deskdot.app.wear.ui.rememberTextInput
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/** "30 s", "2 min", "1 h" (playlist durations, mono). */
internal fun fmtDuration(s: Double): String = when {
    s < 60 -> "${s.toInt()} s"
    s < 3600 -> if (s % 60 == 0.0) "${(s / 60).toInt()} min" else "${(s / 60).toInt()} min ${(s % 60).toInt()} s"
    else -> "${(s / 3600).toInt()} h"
}

/** §5.6 duration stepping: 3–60 s by 1, 60–600 s by 15, 600–3600 s by 60. */
internal val durationStep: (Double, Int) -> Double = { v, d ->
    val step = when {
        d > 0 && v >= 600 || d < 0 && v > 600 -> 60.0
        d > 0 && v >= 60 || d < 0 && v > 60 -> 15.0
        else -> 1.0
    }
    (v + d * step).coerceIn(3.0, 3600.0)
}

/** PUT the whole playlist (the engine validates and pushes the new state). */
internal suspend fun putPlaylist(engine: EngineClient, enabled: Boolean, items: List<PlItem>): Boolean {
    val arr = JSONArray()
    items.forEach { arr.put(it.toJson()) }
    val ok = engine.put("/api/playlist", JSONObject().put("enabled", enabled).put("items", arr)) != null
    engine.refreshState()
    return ok
}

/** Holds the live `/ws` while the composable's lifecycle is RESUMED and [active]. */
@Composable
internal fun LiveState(active: Boolean = true) {
    val dd = LocalDd.current
    val lifecycle = LocalLifecycleOwner.current
    DisposableEffect(lifecycle, active) {
        var held = false
        fun sync(resumed: Boolean) {
            val want = resumed && active
            if (want && !held) { dd.engine.acquireSocket(); held = true }
            if (!want && held) { dd.engine.releaseSocket(); held = false }
        }
        val obs = LifecycleEventObserver { _, e ->
            if (e == Lifecycle.Event.ON_RESUME) sync(true)
            if (e == Lifecycle.Event.ON_PAUSE) sync(false)
        }
        lifecycle.lifecycle.addObserver(obs)
        sync(lifecycle.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
        onDispose {
            lifecycle.lifecycle.removeObserver(obs)
            sync(false)
        }
    }
}

// ================================================================================= §5.6 page

@Composable
fun PlaylistsPage(nav: NavHostController, pager: PagerState) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    val active = pager.active(3)
    LiveState(active)
    val state by dd.engine.state.collectAsState()
    val meta by dd.meta.collectAsState()
    val scope = rememberCoroutineScope()
    var presets by remember { mutableStateOf<List<Preset>>(emptyList()) }
    var menuFor by remember { mutableStateOf<String?>(null) }
    val del = rememberConfirm()
    LaunchedEffect(active) {
        if (!active) return@LaunchedEffect
        dd.loadMeta()
        dd.engine.refreshState()
        presets = dd.engine.getArray("/api/presets").objects().map { Preset.parse(it) }.sortedBy { it.builtin }
    }
    val s = state
    val playing = s?.playing == true
    val list = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus, active)

    fun op(o: String) = scope.launch {
        if (dd.engine.post("/api/playlist/$o") != null) haptics.confirm() else haptics.reject()
        dd.engine.refreshState()
    }

    Box(Modifier.fillMaxSize()) {
        SuiteList(list, focus) {
            item("h") {
                HeaderItem(it, "Playlist", sub = if (s == null) engineWaitText() else if (playing) "Playing · ${s.presetName ?: "Playlist"}" else "Stopped")
            }
            item("t") {
                ActionRowItem(
                    it,
                    listOf(
                        Act(Icons.prev, "Prev", "Previous", mode = LabelMode.OnPress) { op("prev") },
                        if (playing) Act(Icons.stop, "Stop", "Stop", mode = LabelMode.OnPress) { op("stop") } else Act(Icons.play, "Play", "Play", mode = LabelMode.OnPress) { op("play") },
                        Act(Icons.next, "Next", "Next", mode = LabelMode.OnPress) { op("next") },
                    ),
                )
            }
            val items = s?.items.orEmpty()
            items(items, key = { it.id }) { pi, m ->
                PlRow(m, meta?.name(pi.app) ?: pi.app, pi, current = playing && s?.currentItem == pi.id) { nav.plItem(pi.id) }
            }
            if (s != null && items.isEmpty()) item("e") { StatusLineItem(it, "The playlist is empty", look.variantText) }
            if (presets.isNotEmpty()) item("ph") { CaptionItem(it, "Presets") }
            presets.forEach { p ->
                item("p_${p.id}") {
                    SettingItem(
                        it, Icons.viewList, p.name, if (p.count == 1) "1 app" else "${p.count} apps",
                        onClick = {
                            scope.launch {
                                if (dd.engine.post("/api/presets/${p.id}/play") != null) {
                                    haptics.confirm(); toast.show("Playing ${p.name}")
                                } else haptics.reject()
                                dd.engine.refreshState()
                            }
                        },
                        onLongClick = { haptics.longPress(); menuFor = if (menuFor == p.id) null else p.id },
                    )
                }
                if (menuFor == p.id) item("pm_${p.id}") {
                    ActionRowItem(
                        it,
                        buildList {
                            add(Act(Icons.shuffle, "Shuffle", "Shuffle play ${p.name}") {
                                scope.launch {
                                    dd.engine.post("/api/presets/${p.id}/play", JSONObject().put("shuffle", true))
                                    haptics.confirm(); menuFor = null
                                }
                            })
                            if (!p.builtin) add(Act(Icons.close, if (del.armed) "Sure?" else "Delete", "Delete ${p.name}", variant = if (del.armed) Btn.Error else Btn.Neutral) {
                                del.tap(scope) {
                                    scope.launch {
                                        dd.engine.delete("/api/presets/${p.id}")
                                        haptics.confirm()
                                        presets = presets.filter { x -> x.id != p.id }
                                        menuFor = null
                                    }
                                }
                            })
                        },
                    )
                }
            }
            item("acts") {
                ActionRowItem(
                    it,
                    listOf(
                        Act(Icons.playlistAdd, "New", "New playlist") { nav.navigate(Route.PL_NEW) },
                        Act(Icons.shuffle, "Shuffle", "Shuffle the playing preset") {
                            val id = presets.firstOrNull { p -> p.name == s?.presetName }?.id
                            if (id == null) {
                                haptics.reject(); toast.show("No preset playing")
                            } else scope.launch {
                                dd.engine.post("/api/presets/$id/play", JSONObject().put("shuffle", true))
                                haptics.confirm()
                            }
                        },
                    ),
                )
            }
        }
    }
}

/** preview `playlists` item row: h 104; name title-m at −150, duration mono right-aligned at +156; skipped at .5. */
@Composable
private fun PlRow(modifier: Modifier, name: String, pi: PlItem, current: Boolean, onClick: () -> Unit) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    DrawnItem(modifier, 352, 104, description = "$name, ${if (pi.enabled) fmtDuration(pi.duration) else "skipped"}", press = rowPress(look, 352f, 104f, haptics), onClick = onClick) {
        val n = textRun(name, TS.titleM(look.bold), 220f)
        val d = textRun(if (pi.enabled) fmtDuration(pi.duration) else "skipped", TS.mono(24f))
        onDrawBehind {
            val cy = size.height / 2f
            val a = if (pi.enabled) 1f else 0.5f
            if (current) drawCircle(look.roles.accent, 4f, Offset(14f, cy))
            drawRun(n, 26f, cy + 11f, Neutral.onSurface, alpha = a)
            drawRun(d, 332f, cy + 11f, look.variantText, TAlign.InkEnd, a)
        }
    }
}

// =========================================================================== §5.6 item sheet

@Composable
fun PlaylistItemScreen(nav: NavHostController, id: String) {
    val dd = LocalDd.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    LiveState()
    val state by dd.engine.state.collectAsState()
    val meta by dd.meta.collectAsState()
    val scope = rememberCoroutineScope()
    val remove = rememberConfirm()
    val s = state
    val idx = s?.items?.indexOfFirst { it.id == id } ?: -1
    val pi = if (idx >= 0) s!!.items[idx] else null

    fun save(items: List<PlItem>, after: () -> Unit = {}) {
        val st = s ?: return
        scope.launch {
            if (putPlaylist(dd.engine, st.playlistEnabled, items)) { haptics.confirm(); after() } else { haptics.reject(); toast.show("Couldn't save") }
        }
    }

    val list = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(list, focus) {
            item("h") { HeaderItem(it, pi?.let { p -> meta?.name(p.app) ?: p.app } ?: "Item") }
            if (pi == null || s == null) {
                item("w") { StatusLineItem(it, if (s == null) engineWaitText() else "This item is gone", Neutral.onSurfaceVariant) }
                return@SuiteList
            }
            item("dur") {
                SettingItem(it, Icons.hourglass, "Duration", fmtDuration(pi.duration), Trailing.Chevron, onClick = {
                    Pick.number(nav, NumberReq("Duration", pi.duration, 3.0, 3600.0, durationStep, ::fmtDuration) { v ->
                        val cur = dd.engine.state.value ?: return@NumberReq
                        dd.scope.launch { putPlaylist(dd.engine, cur.playlistEnabled, cur.items.map { x -> if (x.id == id) x.copy(duration = v) else x }) }
                    })
                })
            }
            item("inc") {
                SettingItem(it, Icons.check, "Include", null, if (pi.enabled) Trailing.SwitchOn else Trailing.SwitchOff, onClick = {
                    save(s.items.map { x -> if (x.id == id) x.copy(enabled = !x.enabled) else x })
                })
            }
            if (idx > 0) item("up") {
                GlassPillItem(it, "Move up") { save(s.items.toMutableList().apply { add(idx - 1, removeAt(idx)) }) }
            }
            if (idx < s.items.size - 1) item("down") {
                GlassPillItem(it, "Move down") { save(s.items.toMutableList().apply { add(idx + 1, removeAt(idx)) }) }
            }
            item("rm") {
                GlassPillItem(it, if (remove.armed) "Sure?" else "Remove", error = remove.armed) {
                    remove.tap(scope) { save(s.items.filter { x -> x.id != id }) { nav.popBackStack() } }
                }
            }
        }
    }
}

// ======================================================================= §5.6 new playlist flow

@Composable
fun NewPlaylistScreen(nav: NavHostController) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    val meta by dd.meta.collectAsState()
    LaunchedEffect(Unit) { dd.loadMeta() }
    val scope = rememberCoroutineScope()
    var step by remember { mutableStateOf(0) }
    val chosen = remember { mutableStateListOf<String>() }
    val durations = remember { mutableStateMapOf<String, Double>() }
    BackHandler(enabled = step > 0) { step-- }
    val apps = remember(meta) { meta?.apps.orEmpty().filter { it.supported }.sortedBy { it.name.lowercase() } }

    val save = rememberTextInput("Preset name") { name ->
        scope.launch {
            val items = chosen.map { a -> PlItem(java.util.UUID.randomUUID().toString().take(8), a, durations[a] ?: 30.0, true, null) }
            val ok = putPlaylist(dd.engine, true, items) &&
                dd.engine.post("/api/presets", JSONObject().put("name", name.take(40))) != null
            dd.engine.post("/api/playlist/play")
            if (ok) { haptics.confirm(); toast.show("Saved"); nav.popBackStack() } else { haptics.reject(); toast.show("Couldn't save") }
        }
    }

    val list = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        if (step == 0) {
            SuiteList(list, focus) {
                item("h") {
                    DrawnItem(it, 352, 64, description = "Choose apps, ${chosen.size} chosen") {
                        val t = textRun("Choose apps", TS.titleL(look.bold), 260f)
                        val n = textRun(chosen.size.toString(), TStyle(OFont.G700, 24f))
                        onDrawBehind {
                            drawRun(t, 176f, 46f, Neutral.onSurface, TAlign.InkCenter)
                            if (chosen.isNotEmpty()) {
                                val x = 176f + t.inkWidth / 2f + 26f
                                drawCircle(look.roles.accent, 18f, Offset(x, 32f))
                                drawRun(n, x, 40.5f, look.roles.onAccent, TAlign.InkCenter)
                            }
                        }
                    }
                }
                if (meta == null) item("w") { StatusLineItem(it, engineWaitText(), Neutral.onSurfaceVariant) }
                items(apps, key = { it.id }) { a, m ->
                    LetterRowItem(m, a.name, catColor(a.category), trailingCheck = a.id in chosen, onClick = {
                        if (!chosen.remove(a.id)) chosen.add(a.id)
                        haptics.tick()
                    })
                }
                if (chosen.isNotEmpty()) item("next") { GlassPillItem(it, "Review", accent = true) { step = 1 } }
            }
        } else {
            val list2 = rememberSuiteListState()
            val focus2 = remember { FocusRequester() }
            FocusWhenActive(focus2)
            SuiteList(list2, focus2) {
                item("h") { HeaderItem(it, "Review", sub = "${chosen.size} apps") }
                chosen.forEach { a ->
                    item("r_$a") { m ->
                        PlRow(m, meta?.name(a) ?: a, PlItem(a, a, durations[a] ?: 30.0, true, null), false) {
                            Pick.number(nav, NumberReq("Duration", durations[a] ?: 30.0, 3.0, 3600.0, durationStep, ::fmtDuration) { v -> durations[a] = v })
                        }
                    }
                }
                item("save") { GlassPillItem(it, "Save as preset", accent = true, w = 300) { save() } }
            }
        }
    }
}

