package com.deskdot.app.wear.screens

import android.content.Intent
import android.provider.Settings
import android.view.HapticFeedbackConstants
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathOperation
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.navigation.NavHostController
import com.deskdot.app.wear.design.DrawnItem
import com.deskdot.app.wear.design.GlassFactory
import com.deskdot.app.wear.design.GlassKey
import com.deskdot.app.wear.design.GlassVariant
import com.deskdot.app.wear.design.HeaderItem
import com.deskdot.app.wear.design.Icons
import com.deskdot.app.wear.design.LocalHaptics
import com.deskdot.app.wear.design.LocalLook
import com.deskdot.app.wear.design.Neutral
import com.deskdot.app.wear.design.OFont
import com.deskdot.app.wear.design.Semantic
import com.deskdot.app.wear.design.SettingItem
import com.deskdot.app.wear.design.SuiteList
import com.deskdot.app.wear.design.TAlign
import com.deskdot.app.wear.design.TS
import com.deskdot.app.wear.design.TStyle
import com.deskdot.app.wear.design.Trailing
import com.deskdot.app.wear.design.drawGlass
import com.deskdot.app.wear.design.drawIcon
import com.deskdot.app.wear.design.drawRun
import com.deskdot.app.wear.design.pxAt
import com.deskdot.app.wear.design.rememberSuiteListState
import com.deskdot.app.wear.design.textRun
import com.deskdot.app.wear.nav.ChoiceReq
import com.deskdot.app.wear.nav.NumberReq
import com.deskdot.app.wear.nav.Pick
import com.deskdot.app.wear.nav.Route
import com.deskdot.app.wear.nav.game
import com.deskdot.app.wear.nav.gamepad
import com.deskdot.app.wear.net.Lobby
import com.deskdot.app.wear.net.TvLink
import com.deskdot.app.wear.ui.Act
import com.deskdot.app.wear.ui.ActionRowItem
import com.deskdot.app.wear.ui.Btn
import com.deskdot.app.wear.ui.FocusWhenActive
import com.deskdot.app.wear.ui.GlassPillItem
import com.deskdot.app.wear.ui.IconRowItem
import com.deskdot.app.wear.ui.LocalDd
import com.deskdot.app.wear.ui.LocalToast
import com.deskdot.app.wear.ui.QrBrightness
import com.deskdot.app.wear.ui.Screen
import com.deskdot.app.wear.ui.StatusLineItem
import com.deskdot.app.wear.ui.drawQrPlate
import com.deskdot.app.wear.ui.encodeQr
import com.deskdot.app.wear.ui.rememberConfirm
import com.deskdot.app.wear.ui.rememberDotRenderer
import com.deskdot.app.wear.ui.rememberLiveFrames
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import kotlin.math.PI
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

// ==================================================================================== §5.5.1 list

@Composable
fun GamesPage(nav: NavHostController, pager: PagerState) {
    val dd = LocalDd.current
    val meta by dd.meta.collectAsState()
    LaunchedEffect(pager.settledPage == 2) { if (pager.settledPage == 2) dd.loadMeta() }
    val games = remember(meta) { meta?.apps.orEmpty().filter { it.isGame }.sortedBy { it.name.lowercase() } }
    val state = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus, pager.active(2))
    val wait = engineWaitText()
    Box(Modifier.fillMaxSize()) {
        SuiteList(state, focus) {
            item("h") { HeaderItem(it, "Games") }
            if (meta == null) item("w") { StatusLineItem(it, wait, Neutral.onSurfaceVariant) }
            items(games, key = { it.id }) { g, m ->
                IconRowItem(m, Icons.games, g.name, if (g.maxPlayers > 1) "1–${g.maxPlayers} players" else "Solo", dim = !g.supported) { nav.game(g.id) }
            }
            if (meta != null) {
                item("casino") { IconRowItem(it, Icons.grid, "Casino", "Host a table") { nav.navigate(Route.CASINO) } }
                item("tv") { IconRowItem(it, Icons.tv, "TV link", "Show the panel on a TV") { nav.navigate(Route.TV) } }
            }
        }
    }
}

// ================================================================================ §5.5.2 game setup

@Composable
fun GameSetupScreen(nav: NavHostController, id: String) {
    val dd = LocalDd.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    val meta by dd.meta.collectAsState()
    LaunchedEffect(Unit) { dd.loadMeta() }
    val g = meta?.app(id)
    val scope = rememberCoroutineScope()
    var modeId by remember(g) { mutableStateOf(g?.modes?.firstOrNull()?.id) }
    val mode = g?.modes?.firstOrNull { it.id == modeId }
    val minP = mode?.minPlayers ?: 1
    val maxP = mode?.maxPlayers ?: g?.maxPlayers ?: 1
    var players by remember(g, modeId) { mutableIntStateOf(minOf(maxOf(2, minP), maxP)) }
    var ai by remember { mutableStateOf(false) }
    val props = remember(g) { g?.schema?.optJSONObject("properties") }

    fun settings(): JSONObject {
        val s = JSONObject()
        if (props?.has("mode") == true && modeId != null) s.put("mode", modeId)
        if (props?.has("players") == true) s.put("players", players)
        return s
    }

    val state = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(state, focus) {
            item("h") { HeaderItem(it, g?.name ?: "Game") }
            if (g == null) {
                item("w") { StatusLineItem(it, engineWaitText(), Neutral.onSurfaceVariant) }
                return@SuiteList
            }
            if (g.modes.size > 1) item("mode") {
                SettingItem(it, Icons.grid, "Mode", mode?.name ?: "–", Trailing.Chevron, onClick = {
                    Pick.choice(nav, ChoiceReq("Mode", g.modes.map { m -> m.id to m.name }, modeId) { v -> modeId = v })
                })
            }
            if (maxP > 1) item("players") {
                SettingItem(it, Icons.group, "Players", players.toString(), Trailing.Chevron, onClick = {
                    Pick.number(nav, NumberReq("Players", players.toDouble(), minP.toDouble(), maxP.toDouble(), Pick.linear(1.0, minP.toDouble(), maxP.toDouble()), { v -> v.toInt().toString() }) { v -> players = v.toInt() })
                })
            }
            item("acts") {
                ActionRowItem(
                    it,
                    buildList {
                        add(Act(Icons.play, "Solo", "Play solo") {
                            scope.launch {
                                val ok = dd.engine.post("/api/apps/$id/activate", JSONObject().put("settings", settings())) != null
                                if (!ok) { haptics.reject(); toast.show("Engine not reachable"); return@launch }
                                haptics.confirm()
                                nav.gamepad(id)
                            }
                        })
                        if (g.maxPlayers > 1) add(Act(Icons.group, "Host", "Play with friends") {
                            scope.launch {
                                val r = dd.engine.post("/api/play/lobby", JSONObject().put("app", id))
                                if (r == null) { haptics.reject(); toast.show("Couldn't open a room"); return@launch }
                                haptics.confirm()
                                dd.hosting.started(Lobby.parse(r), null)
                                nav.navigate(Route.LOBBY)
                            }
                        })
                        add(Act(Icons.fan, "AI", "Let AI play", variant = if (ai) Btn.On else Btn.Neutral) {
                            ai = !ai
                            haptics.confirm()
                            if (ai) scope.launch {
                                dd.engine.post("/api/apps/$id/activate", JSONObject().put("settings", settings()))
                                dd.engine.post("/api/apps/$id/actions/demo")
                                toast.show("AI is playing")
                            }
                        })
                    },
                )
            }
        }
    }
}

// =============================================================================== QR page (shared)

/**
 * The §5.5.3 page Q layout, shared by the Lobby, the TV link and Studio Share: a white plate centred on C,
 * the host:port line on top (JetBrains Mono Bold, baseline 66, sized to the 229 px chord) and the path line at
 * the bottom (32 px accent-light, baseline 372). Nothing else, so it scans from 30 cm. [hint] replaces nothing:
 * it sits under the bottom line only after the brightness boost timed out.
 */
@Composable
internal fun QrPageLayer(url: String, top: String, bottom: String, hint: String? = null, modifier: Modifier = Modifier) {
    val look = LocalLook.current
    val qr = remember(url) { encodeQr(url) }
    val topSize = minOf(22f, kotlin.math.floor(229f / (0.6f * top.length.coerceAtLeast(1))))
    Spacer(
        modifier.fillMaxSize().drawWithCache {
            val t = textRun(top, TStyle(OFont.M700, topSize))
            val b = textRun(bottom, TStyle(OFont.M700, 32f), 214f)
            val h = hint?.let { textRun(it, TS.labelM(look.bold)) }
            onDrawBehind {
                if (qr != null) drawQrPlate(qr)
                drawRun(t, 208f, 66f, Neutral.onSurface, TAlign.InkCenter)
                drawRun(b, 208f, 372f, look.roles.accentLight, TAlign.InkCenter)
                if (h != null) drawRun(h, 208f, 398f, look.variantText, TAlign.InkCenter)
            }
        },
    )
}

/** "http://192.168.1.73:8765/p/ABCD" → ("192.168.1.73:8765", "/p/ABCD"). */
internal fun splitUrl(url: String): Pair<String, String> {
    val noScheme = url.substringAfter("://")
    val host = noScheme.substringBefore('/')
    val path = "/" + noScheme.substringAfter('/', "")
    return host to path.trimEnd('/').ifEmpty { "/" }
}

/** Two dots at the right edge for the vertical pager (§5.5.3): (398, 196) and (398, 220), r 3. */
private fun androidx.compose.ui.graphics.drawscope.DrawScope.vDots(page: Int) {
    drawCircle(if (page == 0) Neutral.onSurface else Neutral.outline, 3f, Offset(398f, 196f))
    drawCircle(if (page == 1) Neutral.onSurface else Neutral.outline, 3f, Offset(398f, 220f))
}

// ================================================================================== §5.5.3 lobby

@Composable
fun LobbyScreen(nav: NavHostController) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    val ctx = LocalContext.current
    val meta by dd.meta.collectAsState()
    val scope = rememberCoroutineScope()
    var lobby by remember { mutableStateOf<Lobby?>(null) }
    var loaded by remember { mutableStateOf(false) }
    var started by remember { mutableStateOf(false) }
    var dimmed by remember { mutableStateOf(false) }
    val end = rememberConfirm()
    val pager = rememberPagerState { 2 }
    val lifecycle = LocalLifecycleOwner.current

    // Roster: GET /api/play/lobby every 2 s, only while this screen is RESUMED.
    LaunchedEffect(lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                val r = dd.engine.get("/api/play/lobby")
                if (r != null) {
                    val l = Lobby.parse(r.optJSONObject("lobby"))
                    if (l == null && loaded) {
                        dd.hosting.ended()
                        nav.popBackStack()
                        return@repeatOnLifecycle
                    }
                    lobby = l
                    loaded = true
                    if (l != null) dd.hosting.started(l, null)
                }
                delay(2_000)
            }
        }
    }
    val l = lobby
    val url = l?.url ?: ""
    val (top, path) = splitUrl(url)
    val isCasino = meta?.app(l?.app)?.isCasino == true
    QrBrightness(enabled = pager.currentPage == 0 && !started && !dimmed && l?.lanReady == true, maxMs = if (look.calm) 120_000 else 300_000) { dimmed = true }

    Screen(timeText = pager.currentPage == 1) {
        VerticalPager(state = pager, modifier = Modifier.fillMaxSize()) { page ->
            if (page == 0) {
                when {
                    l == null -> Box(Modifier.fillMaxSize()) {
                        StatusLineItem(Modifier.pxAt(32, 184, 352, 48), if (loaded) "No room open" else "Opening room…", Neutral.onSurfaceVariant)
                    }
                    !l.lanReady -> Box(Modifier.fillMaxSize()) {
                        WarnCardItem(Modifier.pxAt(43, 120, 330, 108), "Connect the watch to Wi-Fi to host")
                        GlassPillItem(Modifier.pxAt(88, 250, 240, 96), "Wi-Fi settings") {
                            runCatching { ctx.startActivity(Intent(Settings.ACTION_WIFI_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                        }
                    }
                    started -> InGamePreview(l.code)
                    else -> QrPageLayer(
                        url, top, path, hint = if (dimmed) "Tap to brighten" else null,
                        modifier = Modifier
                            .semantics { contentDescription = "Join code ${l.code.toList().joinToString(" ")}, address ${top.substringBefore(':')} port ${top.substringAfter(':', "8765")}" }
                            .pointerInput(Unit) { detectTapGestures { dimmed = false } },
                    )
                }
            } else {
                val state = rememberSuiteListState()
                val focus = remember { FocusRequester() }
                FocusWhenActive(focus, pager.currentPage == 1)
                SuiteList(state, focus) {
                    item("h") {
                        DrawnItem(it, 352, 104, description = "Players ${l?.seats?.size ?: 0} of ${l?.maxPlayers ?: 0}, room ${l?.code}") {
                            val t = textRun("Players ${l?.seats?.size ?: 0} / ${l?.maxPlayers ?: 4}", TS.titleM(look.bold))
                            val c = textRun(l?.code ?: "", TS.mono(26f))
                            onDrawBehind {
                                drawRun(t, 176f, 44f, Neutral.onSurface, TAlign.InkCenter)
                                drawRun(c, 176f, 84f, look.roles.accentLight, TAlign.InkCenter)
                            }
                        }
                    }
                    val max = l?.maxPlayers ?: 4
                    for (seat in 1..max) {
                        val s = l?.seats?.firstOrNull { it.seat == seat }
                        item("s$seat") { SeatRow(it, seat, s?.name, s?.color, s?.ready == true) }
                    }
                    if (isCasino && l != null) {
                        item("next") {
                            GlassPillItem(it, "Next round") {
                                scope.launch {
                                    val ok = dd.engine.post("/api/apps/${l.app}/actions/casino", JSONObject().put("op", "start_round")) != null
                                    if (ok) haptics.confirm() else haptics.reject()
                                }
                            }
                        }
                        item("switch") {
                            GlassPillItem(it, "Switch table") {
                                val tables = meta?.apps.orEmpty().filter { a -> a.isCasino }.map { a -> a.id to a.name }
                                Pick.choice(nav, ChoiceReq("Table", tables, l.app) { v ->
                                    dd.scope.launch { dd.engine.post("/api/play/lobby/switch", JSONObject().put("app", v)) }
                                })
                            }
                        }
                    }
                    item("acts") {
                        ActionRowItem(
                            it,
                            buildList {
                                if (!started) add(Act(Icons.play, "Start", "Start the match", variant = Btn.On) {
                                    scope.launch {
                                        if (dd.engine.post("/api/play/lobby/start") != null) {
                                            haptics.confirm()
                                            started = true
                                            pager.animateScrollToPage(0)
                                        } else {
                                            haptics.reject()
                                        }
                                    }
                                })
                                add(Act(Icons.qr, if (started) "Panel" else "QR", "Show the join code") { scope.launch { pager.animateScrollToPage(0) } })
                                add(Act(Icons.close, if (end.armed) "Sure?" else "End", "End the game", variant = if (end.armed) Btn.Error else Btn.Neutral) {
                                    end.tap(scope) {
                                        scope.launch {
                                            dd.engine.delete("/api/play/lobby")
                                            haptics.confirm()
                                            dd.hosting.ended()
                                            nav.popBackStack()
                                        }
                                    }
                                })
                            },
                        )
                    }
                }
            }
        }
        Spacer(Modifier.fillMaxSize().drawBehind { vDots(pager.currentPage) })
    }
}

/** After Start, page Q becomes the live panel (pitch 6, centred) with the room code under it. */
@Composable
private fun InGamePreview(code: String) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val renderer = rememberDotRenderer(6, 2.25f)
    val tick = rememberLiveFrames(dd.engine, renderer, if (look.le) 1f else if (look.calm) 4f else 10f, look.le)
    Spacer(
        Modifier.fillMaxSize().drawWithCache {
            val c = textRun(code, TStyle(OFont.M700, 32f))
            onDrawBehind {
                tick.intValue
                drawImage(renderer.image, Offset(112f, 100f))
                drawRun(c, 208f, 340f, look.roles.accentLight, TAlign.InkCenter)
            }
        },
    )
}

/** preview `lobbyPlayers` seat row: h 104; 24 px seat-colour dot at −140, name at −112, ✓ at +140 when ready. */
@Composable
private fun SeatRow(modifier: Modifier, seat: Int, name: String?, color: String?, ready: Boolean) {
    val look = LocalLook.current
    val seatColor = remember(color, seat) {
        runCatching { Color(android.graphics.Color.parseColor(color ?: SEAT_COLORS[seat - 1])) }.getOrDefault(Color(0xFF00C8FF))
    }
    DrawnItem(modifier, 352, 104, description = if (name != null) "Seat $seat, $name${if (ready) ", ready" else ""}" else "Seat $seat, open") {
        val n = name?.let { textRun(it, TS.titleM(look.bold), 220f) }
        val open = textRun("Open seat", TS.body26(look.bold))
        onDrawBehind {
            val cy = size.height / 2f
            drawCircle(seatColor, 12f, Offset(36f, cy), alpha = if (n == null) 0.45f else 1f)
            if (n != null) {
                drawRun(n, 64f, cy + 11f, Neutral.onSurface)
                if (ready) drawIcon(Icons.check, 316f, cy, 32f, Semantic.ok)
            } else {
                drawRun(open, 64f, cy + 10f, look.variantText)
            }
        }
    }
}

private val SEAT_COLORS = listOf("#00c8ff", "#ff3c5a", "#50ff78", "#ffc800", "#b48cff", "#ff7ab6", "#8fd16a", "#ffffff")

// ================================================================================ §5.5.5 gamepad

private enum class Zone(val key: String) { Up("up"), Right("right"), Down("down"), Left("left"), A("a"), B("b") }

/**
 * §5.5.5 the watch as a controller: a d-pad ring (r 108–200, four wedges centred on 0/90/180/270° with dark gaps
 * along the diagonals) and a centre disc split into B (left) and A (right). Input is sent on touch-down over the
 * WebSocket (held only while this screen is RESUMED) with a VIRTUAL_KEY haptic.
 */
@Composable
fun GamepadScreen(id: String) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val view = LocalView.current
    val lifecycle = LocalLifecycleOwner.current
    var pressed by remember { mutableStateOf<Set<Zone>>(emptySet()) }
    DisposableEffect(lifecycle) {
        val obs = androidx.lifecycle.LifecycleEventObserver { _, e ->
            if (e == Lifecycle.Event.ON_RESUME) dd.engine.acquireSocket()
            if (e == Lifecycle.Event.ON_PAUSE) dd.engine.releaseSocket()
        }
        lifecycle.lifecycle.addObserver(obs)
        onDispose {
            lifecycle.lifecycle.removeObserver(obs)
            if (lifecycle.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) dd.engine.releaseSocket()
        }
    }
    val outer = remember(look.le) { if (look.le) null else GlassFactory.get(GlassKey(400, 400, 200f, GlassVariant.Neutral)) }
    val inner = remember(look.le) { if (look.le) null else GlassFactory.get(GlassKey(192, 192, 96f, GlassVariant.Neutral)) }

    fun zoneAt(x: Float, y: Float): Zone? {
        val dx = x - 208f
        val dy = y - 208f
        val r = sqrt(dx * dx + dy * dy)
        return when {
            r <= 96f -> if (dx < 0) Zone.B else Zone.A
            r in 104f..206f -> {
                val ang = ((atan2(dx.toDouble(), (-dy).toDouble()) * 180.0 / PI) + 360.0) % 360.0
                when {
                    ang >= 315 || ang < 45 -> Zone.Up
                    ang < 135 -> Zone.Right
                    ang < 225 -> Zone.Down
                    else -> Zone.Left
                }
            }
            else -> null
        }
    }

    Spacer(
        Modifier.fillMaxSize()
            .semantics { contentDescription = "Gamepad: arrows around the edge, B and A in the middle" }
            .pointerInput(id) {
                awaitEachGesture {
                    while (true) {
                        val ev = awaitPointerEvent()
                        val now = HashSet<Zone>()
                        ev.changes.forEach { c ->
                            if (c.pressed) zoneAt(c.position.x, c.position.y)?.let { z -> now.add(z) }
                        }
                        val fresh = now - pressed
                        fresh.forEach { z ->
                            view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                            dd.engine.sendInput(id, z.key)
                        }
                        pressed = now
                        ev.changes.forEach { it.consume() }
                        if (ev.changes.none { it.pressed }) break
                    }
                    pressed = emptySet()
                }
            }
            .drawWithCache {
                val ring = Path().apply {
                    addOval(androidx.compose.ui.geometry.Rect(Offset(208f, 208f), 200f))
                }
                val hole = Path().apply { addOval(androidx.compose.ui.geometry.Rect(Offset(208f, 208f), 108f)) }
                val annulus = Path().apply { op(ring, hole, PathOperation.Difference) }
                val wedges = Zone.entries.take(4).mapIndexed { i, _ ->
                    val sector = Path().apply {
                        moveTo(208f, 208f)
                        arcTo(androidx.compose.ui.geometry.Rect(Offset(208f, 208f), 210f), -135f + i * 90f, 90f, false)
                        close()
                    }
                    Path().apply { op(annulus, sector, PathOperation.Intersect) }
                }
                val left = Path().apply { addRect(androidx.compose.ui.geometry.Rect(112f, 112f, 206f, 304f)) }
                val right = Path().apply { addRect(androidx.compose.ui.geometry.Rect(210f, 112f, 304f, 304f)) }
                val disc = Path().apply { addOval(androidx.compose.ui.geometry.Rect(Offset(208f, 208f), 96f)) }
                val bHalf = Path().apply { op(disc, left, PathOperation.Intersect) }
                val aHalf = Path().apply { op(disc, right, PathOperation.Intersect) }
                val bRun = textRun("B", TStyle(OFont.G800R, 48f))
                val aRun = textRun("A", TStyle(OFont.G800R, 48f))
                val outline = Stroke(4f)
                onDrawBehind {
                    if (outer != null && inner != null) {
                        clipPath(annulus) { drawGlass(outer, 8f, 8f) }
                        drawGlass(inner, 112f, 112f)
                    } else {
                        wedges.forEach { w -> drawPath(w, Neutral.outline, style = outline) }
                        drawPath(bHalf, Neutral.outline, style = outline)
                        drawPath(aHalf, Neutral.outline, style = outline)
                    }
                    // diagonal gaps and the A/B split
                    for (k in 0 until 4) {
                        val a = Math.toRadians(45.0 + 90.0 * k)
                        val s = sin(a).toFloat()
                        val c = cos(a).toFloat()
                        drawLine(Color.Black, Offset(208f + 100f * s, 208f - 100f * c), Offset(208f + 210f * s, 208f - 210f * c), 6f)
                    }
                    drawRect(Color.Black, Offset(206f, 108f), androidx.compose.ui.geometry.Size(4f, 200f))
                    val p = pressed
                    Zone.entries.take(4).forEachIndexed { i, z -> if (z in p) drawPath(wedges[i], Color(0x24FFFFFF)) }
                    if (Zone.B in p) drawPath(bHalf, Color(0x24FFFFFF))
                    if (Zone.A in p) drawPath(aHalf, Color(0x24FFFFFF))
                    for (i in 0 until 4) {
                        val a = Math.toRadians(90.0 * i)
                        val cx = 208f + 154f * sin(a).toFloat()
                        val cy = 208f - 154f * cos(a).toFloat()
                        rotate(90f * i, Offset(cx, cy)) { drawIcon(Icons.chevronUp, cx, cy, 40f, Neutral.onSurface) }
                    }
                    drawRun(bRun, 172f, 225.2f, Neutral.onSurface, TAlign.InkCenter)
                    drawRun(aRun, 244f, 225.2f, Neutral.onSurface, TAlign.InkCenter)
                }
            },
    )
}

// ============================================================================ §5.5.4 casino and TV

@Composable
fun CasinoScreen(nav: NavHostController) {
    val dd = LocalDd.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    val meta by dd.meta.collectAsState()
    LaunchedEffect(Unit) { dd.loadMeta() }
    val tables = remember(meta) { meta?.apps.orEmpty().filter { it.isCasino }.sortedBy { it.name.lowercase() } }
    val scope = rememberCoroutineScope()
    val state = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(state, focus) {
            item("h") { HeaderItem(it, "Casino") }
            if (meta == null) item("w") { StatusLineItem(it, engineWaitText(), Neutral.onSurfaceVariant) }
            items(tables, key = { it.id }) { t, m ->
                IconRowItem(m, Icons.grid, t.name, "Up to ${t.maxPlayers} players", dim = !t.supported) {
                    scope.launch {
                        val r = dd.engine.post("/api/play/lobby", JSONObject().put("app", t.id))
                        if (r == null) { haptics.reject(); toast.show("Couldn't open the table"); return@launch }
                        haptics.confirm()
                        dd.hosting.started(Lobby.parse(r), null)
                        nav.navigate(Route.LOBBY)
                    }
                }
            }
        }
    }
}

@Composable
fun TvScreen(nav: NavHostController) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    var tv by remember { mutableStateOf<TvLink?>(null) }
    var failed by remember { mutableStateOf(false) }
    var dimmed by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val pager = rememberPagerState { 2 }
    LaunchedEffect(Unit) {
        if (!dd.engine.awaitReady(20_000)) { failed = true; return@LaunchedEffect }
        val r = dd.engine.post("/api/tv")
        tv = TvLink.parse(r)
        failed = tv == null
        tv?.let { dd.hosting.started(null, it) }
    }
    val t = tv
    QrBrightness(enabled = pager.currentPage == 0 && t != null && !dimmed, maxMs = if (look.calm) 120_000 else 300_000) { dimmed = true }
    Screen(timeText = pager.currentPage == 1) {
        VerticalPager(state = pager, modifier = Modifier.fillMaxSize()) { page ->
            if (page == 0) {
                if (t == null) {
                    Box(Modifier.fillMaxSize()) {
                        StatusLineItem(Modifier.pxAt(32, 184, 352, 48), if (failed) "Couldn't open the TV link" else "Opening TV link…", Neutral.onSurfaceVariant)
                    }
                } else {
                    val (top, path) = splitUrl(t.url)
                    QrPageLayer(
                        t.url, top, path, hint = if (dimmed) "Tap to brighten" else null,
                        modifier = Modifier
                            .semantics { contentDescription = "TV link ${t.code.toList().joinToString(" ")}, address $top" }
                            .pointerInput(Unit) { detectTapGestures { dimmed = false } },
                    )
                }
            } else {
                val state = rememberSuiteListState()
                val focus = remember { FocusRequester() }
                FocusWhenActive(focus, pager.currentPage == 1)
                SuiteList(state, focus) {
                    item("h") { HeaderItem(it, "TV") }
                    item("look") {
                        val cur = t?.look ?: "led"
                        SettingItem(it, Icons.display, "Look", cur.replaceFirstChar { c -> c.uppercase() }.replace("Led", "LED"), Trailing.Chevron, onClick = {
                            Pick.choice(nav, ChoiceReq("Look", listOf("pixel" to "Pixel", "led" to "LED", "glow" to "Glow"), cur) { v ->
                                dd.scope.launch {
                                    dd.engine.post("/api/tv/settings", JSONObject().put("look", v))
                                    tv = tv?.copy(look = v)
                                }
                            })
                        })
                    }
                    item("close") {
                        GlassPillItem(it, "Close link", error = true) {
                            scope.launch {
                                dd.engine.delete("/api/tv")
                                haptics.confirm()
                                dd.hosting.ended()
                                nav.popBackStack()
                            }
                        }
                    }
                }
            }
        }
        Spacer(Modifier.fillMaxSize().drawBehind { vDots(pager.currentPage) })
    }
}
