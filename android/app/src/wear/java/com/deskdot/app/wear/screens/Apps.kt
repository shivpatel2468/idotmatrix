package com.deskdot.app.wear.screens

import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.PagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.rotary.onRotaryScrollEvent
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
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
import com.deskdot.app.wear.design.OIcon
import com.deskdot.app.wear.design.SettingItem
import com.deskdot.app.wear.design.SpringToken
import com.deskdot.app.wear.design.SuiteList
import com.deskdot.app.wear.design.SuiteListState
import com.deskdot.app.wear.design.TAlign
import com.deskdot.app.wear.design.TS
import com.deskdot.app.wear.design.TStyle
import com.deskdot.app.wear.design.Trailing
import com.deskdot.app.wear.design.drawGlass
import com.deskdot.app.wear.design.drawIcon
import com.deskdot.app.wear.design.drawRun
import com.deskdot.app.wear.design.outlinePill
import com.deskdot.app.wear.design.rememberSuiteListState
import com.deskdot.app.wear.design.rowPress
import com.deskdot.app.wear.design.textRun
import com.deskdot.app.wear.nav.ChoiceReq
import com.deskdot.app.wear.nav.ColorReq
import com.deskdot.app.wear.nav.NumberReq
import com.deskdot.app.wear.nav.Pick
import com.deskdot.app.wear.nav.Route
import com.deskdot.app.wear.nav.app
import com.deskdot.app.wear.nav.appList
import com.deskdot.app.wear.nav.search
import com.deskdot.app.wear.net.AppMeta
import com.deskdot.app.wear.net.Meta
import com.deskdot.app.wear.net.Readiness
import com.deskdot.app.wear.net.objects
import com.deskdot.app.wear.ui.FavouritesRowItem
import com.deskdot.app.wear.ui.FocusWhenActive
import com.deskdot.app.wear.ui.GlassPillItem
import com.deskdot.app.wear.ui.LetterRowItem
import com.deskdot.app.wear.ui.LocalDd
import com.deskdot.app.wear.ui.LocalToast
import com.deskdot.app.wear.ui.Screen
import com.deskdot.app.wear.ui.SearchPillItem
import com.deskdot.app.wear.ui.StatusLineItem
import com.deskdot.app.wear.ui.TextBlockItem
import com.deskdot.app.wear.ui.rememberConfirm
import com.deskdot.app.wear.ui.rememberTextInput
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.text.Collator
import java.text.Normalizer
import kotlin.math.PI
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

// ============================================================================== shared app helpers

internal data class Cat(val id: String, val label: String, val color: Color)

/** §5.4 studio categories (web/src/components/Icon.tsx CATEGORY_LABEL) and their colours. Games/casino live on Games. */
internal val CATS = listOf(
    Cat("time", "Time", Color(0xFF6CC4FF)),
    Cat("data", "Live data", Color(0xFF8FD16A)),
    Cat("media", "Media", Color(0xFFFF4818)),
    Cat("creative", "Create", Color(0xFFFFC24A)),
    Cat("ambient", "Ambient", Color(0xFFB48CFF)),
    Cat("productivity", "Focus & agents", Color(0xFFC9CED6)),
    Cat("pets", "Pets & characters", Color(0xFFFF7AB6)),
    Cat("device", "Panel", Color(0xFF7C828C)),
)

internal fun catColor(id: String): Color = CATS.firstOrNull { it.id == id }?.color ?: when (id) {
    "games", "casino" -> Color(0xFFFF7A4D)
    else -> Color(0xFF7C828C)
}

private val collator: Collator = Collator.getInstance().apply { strength = Collator.PRIMARY }

/** The apps the Apps page lists (everything except games and casino tables), A→Z. */
internal fun Meta.panelApps(): List<AppMeta> = apps.filter { !it.isGame && !it.isCasino }.sortedWith { a, b -> collator.compare(a.name, b.name) }

internal fun fold(s: String): String = Normalizer.normalize(s, Normalizer.Form.NFD).replace(Regex("\\p{M}+"), "").lowercase()

/** "Starting engine…" / "Engine off" placeholder while meta isn't there. */
@Composable
internal fun engineWaitText(): String {
    val dd = LocalDd.current
    val r by dd.engine.readiness.collectAsState()
    return if (r == Readiness.Down) "The engine isn't running" else "Starting engine…"
}

/** A §4.9 settings row whose leading element is a 24 px colour dot (preview rowSetting with a '#' icon). */
@Composable
internal fun DotSettingItem(modifier: Modifier, dot: Color, title: String, value: String?, onClick: () -> Unit) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val h = if (look.le) 120 else 104
    DrawnItem(modifier, 352, h, description = listOfNotNull(title, value).joinToString(", "), press = rowPress(look, 352f, h.toFloat(), haptics), onClick = onClick) {
        val t = textRun(title, TS.labelL(look.bold), 248f)
        val v = value?.let { textRun(it, TS.body26(look.bold), 248f) }
        onDrawBehind {
            val cy = size.height / 2f
            if (look.le) outlinePill(0f, 0f, 352f, size.height, sw = 2f) else drawRoundRect(Neutral.surface1, cornerRadius = CornerRadius(size.height / 2f))
            drawCircle(if (look.le) com.deskdot.app.wear.ui.grey(dot) else dot, 12f, Offset(48f, cy))
            drawRun(t, 84f, cy + if (v != null) -6f else 10f, Neutral.onSurface)
            if (v != null) drawRun(v, 84f, cy + 26f, look.variantText)
        }
    }
}

// ================================================================================ §5.4 Apps page

@Composable
fun AppsPage(nav: NavHostController, pager: PagerState) {
    val dd = LocalDd.current
    val meta by dd.meta.collectAsState()
    val favs by dd.prefs.favourites.collectAsState()
    LaunchedEffect(pager.settledPage == 1) { if (pager.settledPage == 1) dd.loadMeta() }
    val state = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus, pager.active(1))
    val search = rememberTextInput("Search apps") { nav.search(it) }
    val wait = engineWaitText()
    val m = meta
    val apps = remember(m) { m?.panelApps().orEmpty() }
    val counts = remember(apps) { apps.groupingBy { it.category }.eachCount() }
    val favApps = remember(m, favs) { favs.mapNotNull { m?.app(it) } }

    Box(Modifier.fillMaxSize()) {
        SuiteList(state, focus) {
            item("h") { HeaderItem(it, "Apps") }
            item("s") { SearchPillItem(it) { search() } }
            if (favApps.isNotEmpty()) {
                item("f") {
                    FavouritesRowItem(it, favApps.take(3).map { a -> a.name to catColor(a.category) }) { i -> nav.app(favApps[i].id) }
                }
                if (favApps.size > 3) item("f2") {
                    FavouritesRowItem(it, favApps.drop(3).map { a -> a.name to catColor(a.category) }) { i -> nav.app(favApps[3 + i].id) }
                }
            }
            if (m == null) {
                item("w") { StatusLineItem(it, wait, Neutral.onSurfaceVariant) }
            } else {
                CATS.filter { (counts[it.id] ?: 0) > 0 }.forEach { c ->
                    item("c_${c.id}") {
                        val n = counts[c.id] ?: 0
                        DotSettingItem(it, c.color, c.label, if (n == 1) "1 app" else "$n apps") { nav.appList(c.id) }
                    }
                }
                item("az") { SettingItem(it, Icons.grid, "All apps A–Z", "${apps.size} apps", Trailing.Chevron, onClick = { nav.appList("") }) }
            }
        }
    }
}

// ===================================================================== §5.4 app list + §4.4.1 scrub

@Composable
fun AppListScreen(nav: NavHostController, cat: String) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val meta by dd.meta.collectAsState()
    LaunchedEffect(Unit) { dd.loadMeta() }
    val apps = remember(meta, cat) { meta?.panelApps().orEmpty().filter { cat.isEmpty() || it.category == cat } }
    val title = if (cat.isEmpty()) "All apps" else CATS.firstOrNull { it.id == cat }?.label ?: cat
    val state = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    var scrub by remember { mutableStateOf(false) }
    FocusWhenActive(focus, !scrub)
    val scope = rememberCoroutineScope()
    val lens = remember(look.le) { if (look.le) null else GlassFactory.get(GlassKey(368, 120, 60f, GlassVariant.Lens)) }
    val wait = engineWaitText()

    Screen(timeText = !scrub) {
        SuiteList(
            state, focus,
            under = {
                // §4.2.4 lens: only while an app row (index ≥ 1) sits snapped at the centre.
                val i = state.snappedIndex
                if (i >= 1) {
                    if (lens != null) drawGlass(lens, 24f, 148f) else drawRoundRect(look.roles.accent, Offset(34f, 150f), Size(348f, 116f), CornerRadius(58f), style = Stroke(4f))
                }
            },
            onFastCrown = { if (apps.size > 12) scrub = true },
        ) {
            item("h") { HeaderItem(it, title, sub = if (apps.isEmpty()) null else "${apps.size} apps") }
            if (meta == null) item("w") { StatusLineItem(it, wait, Neutral.onSurfaceVariant) }
            items(apps, key = { it.id }) { a, m ->
                AppRow(m, a) { nav.app(a.id) }
            }
        }
        if (scrub) {
            AlphabetScrub(apps, onClose = { scrub = false }) { letterIndex ->
                scrub = false
                scope.launch { state.animateToCentre(1 + letterIndex) }
            }
        }
    }
}

@Composable
internal fun AppRow(modifier: Modifier, a: AppMeta, onClick: () -> Unit) {
    LetterRowItem(
        modifier, a.name, catColor(a.category),
        sub = if (a.supported) null else "Not on this watch",
        dim = !a.supported,
        onClick = if (a.supported) onClick else null,
    )
}

private const val LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ#"

private fun letterOf(name: String): Char {
    val c = fold(name).firstOrNull()?.uppercaseChar() ?: '#'
    return if (c in 'A'..'Z') c else '#'
}

/**
 * §4.4.1 alphabet scrub: scrim 94 %, 27 glyphs on r 186, the active letter big in the centre with its app count.
 * Crown: 48 rotary px per letter (empty letters skipped) with CLOCK_TICK; commit after 800 ms idle, on tap or
 * on drag release.
 */
@Composable
private fun AlphabetScrub(apps: List<AppMeta>, onClose: () -> Unit, onCommit: (Int) -> Unit) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val firstIndex = remember(apps) {
        val m = HashMap<Char, Int>()
        apps.forEachIndexed { i, a -> m.putIfAbsent(letterOf(a.name), i) }
        m
    }
    val counts = remember(apps) { apps.groupingBy { letterOf(it.name) }.eachCount() }
    val present = remember(counts) { LETTERS.filter { (counts[it] ?: 0) > 0 } }
    var active by remember { mutableIntStateOf(LETTERS.indexOf(present.firstOrNull() ?: 'A').coerceAtLeast(0)) }
    var lastInput by remember { mutableIntStateOf(0) }
    val open = remember { Animatable(if (look.motion.cut) 1f else 0f) }
    val focus = remember { FocusRequester() }
    var acc by remember { mutableFloatStateOf(0f) }
    LaunchedEffect(Unit) {
        runCatching { focus.requestFocus() }
        open.animateTo(1f, look.motion.spring(SpringToken.SpatialSlow))
    }
    fun commit() = onCommit(firstIndex[LETTERS[active]] ?: 0)
    LaunchedEffect(lastInput) {
        delay(800)
        commit()
    }
    fun move(dir: Int) {
        if (present.isEmpty()) return
        var i = active
        repeat(LETTERS.length) {
            i = (i + dir).coerceIn(0, LETTERS.length - 1)
            if ((counts[LETTERS[i]] ?: 0) > 0) {
                if (i != active) {
                    active = i
                    haptics.tick()
                } else {
                    haptics.reject()
                }
                return
            }
        }
    }
    fun pickAt(x: Float, y: Float) {
        val ang = ((atan2((x - 208f).toDouble(), (208f - y).toDouble()) * 180.0 / PI) + 360.0) % 360.0
        var k = (ang / (360.0 / 27.0)).roundToInt() % 27
        if ((counts[LETTERS[k]] ?: 0) == 0) {
            // nearest letter that has apps
            k = present.minByOrNull { c -> val d = kotlin.math.abs(LETTERS.indexOf(c) - k); minOf(d, 27 - d) }?.let { LETTERS.indexOf(it) } ?: k
        }
        if (k != active) {
            active = k
            haptics.tick()
        }
    }
    Spacer(
        Modifier.fillMaxSize()
            .semantics { contentDescription = "Alphabet. ${LETTERS[active]}, ${counts[LETTERS[active]] ?: 0} apps" }
            .onRotaryScrollEvent { e ->
                acc += e.verticalScrollPixels
                while (acc >= 48f) { acc -= 48f; move(1); lastInput++ }
                while (acc <= -48f) { acc += 48f; move(-1); lastInput++ }
                true
            }
            .focusRequester(focus)
            .focusable()
            .pointerInput(Unit) { detectTapGestures { pickAt(it.x, it.y); commit() } }
            .pointerInput(Unit) {
                detectDragGestures(onDragEnd = { commit() }, onDragCancel = { onClose() }) { ch, _ -> pickAt(ch.position.x, ch.position.y) }
            }
            .graphicsLayer {
                val p = open.value
                alpha = p.coerceIn(0f, 1f)
            }
            .drawWithCache {
                val ring = LETTERS.map { textRun(it.toString(), TS.labelM(look.bold)) }
                val big = LETTERS.map { textRun(it.toString(), TStyle(OFont.G800R, 28f)) }
                val centre = LETTERS.map { textRun(it.toString(), TStyle(OFont.G800R, 120f)) }
                val countRuns = LETTERS.map { c -> val n = counts[c] ?: 0; textRun(if (n == 1) "1 app" else "$n apps", TS.labelM(look.bold)) }
                onDrawBehind {
                    drawRect(Color(0xF0000000))
                    val k = 0.85f + 0.15f * open.value
                    for (i in LETTERS.indices) {
                        val a = i * (2.0 * PI / 27.0)
                        val x = 208f + (186f * k) * sin(a).toFloat()
                        val y = 208f - (186f * k) * cos(a).toFloat()
                        if (i == active) {
                            drawRun(big[i], x, y + 10f, if (look.le) Neutral.onSurface else look.roles.accent, TAlign.InkCenter)
                            drawCircle(look.roles.accent, 3f, Offset(208f + 160f * k * sin(a).toFloat(), 208f - 160f * k * cos(a).toFloat()))
                        } else {
                            val has = (counts[LETTERS[i]] ?: 0) > 0
                            drawRun(ring[i], x, y + 8.5f, look.variantText, TAlign.InkCenter, if (has) 1f else 0.38f)
                        }
                    }
                    drawRun(centre[active], 208f, 230f, look.roles.accent, TAlign.InkCenter)
                    drawRun(countRuns[active], 208f, 274f, look.variantText, TAlign.InkCenter)
                }
            },
    )
}

// ============================================================================ §4.4.2 search results

@Composable
fun SearchScreen(nav: NavHostController, q: String) {
    val dd = LocalDd.current
    val look = LocalLook.current
    val meta by dd.meta.collectAsState()
    LaunchedEffect(Unit) { dd.loadMeta() }
    val results = remember(meta, q) {
        val key = fold(q.trim())
        val all = meta?.panelApps().orEmpty()
        val prefix = all.filter { fold(it.name).startsWith(key) }
        val contains = all.filter { it !in prefix && (fold(it.name).contains(key) || fold(it.description).contains(key)) }
        prefix + contains
    }
    val again = rememberTextInput("Search apps") { t ->
        nav.popBackStack()
        nav.search(t)
    }
    val state = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(state, focus) {
            item("q") {
                DrawnItem(it, 352, 64, description = "Results for $q") {
                    val r = textRun("“$q”", TS.titleM(look.bold), 330f)
                    onDrawBehind { drawRun(r, 176f, 43f, look.accentText, TAlign.InkCenter) }
                }
            }
            if (meta != null && results.isEmpty()) {
                item("none") { TextBlockItem(it, "No apps match") }
                item("again") { GlassPillItem(it, "Try again") { again() } }
            }
            items(results, key = { it.id }) { a, m -> AppRow(m, a) { nav.app(a.id) } }
        }
    }
}

// ================================================================================ §5.4 app detail

private sealed interface Prop {
    val key: String
    val title: String

    data class Bool(override val key: String, override val title: String) : Prop
    data class Choice(override val key: String, override val title: String, val options: List<Pair<String, String>>) : Prop
    data class Num(override val key: String, override val title: String, val min: Double, val max: Double, val integer: Boolean) : Prop
    data class Colour(override val key: String, override val title: String) : Prop
    data class Text(override val key: String, override val title: String) : Prop
}

private fun parseProps(schema: JSONObject?): Pair<List<Prop>, Map<String, Any?>> {
    val props = schema?.optJSONObject("properties") ?: return emptyList<Prop>() to emptyMap()
    val out = ArrayList<Prop>()
    val defaults = HashMap<String, Any?>()
    var unsupported = false
    for (k in props.keys()) {
        val p = props.optJSONObject(k) ?: continue
        val plats = p.optJSONArray("platforms")
        if (plats != null && (0 until plats.length()).none { plats.optString(it) == "android" }) continue
        val title = p.optString("title", k.replace('_', ' ').replaceFirstChar { it.uppercase() })
        defaults[k] = if (p.has("default")) p.opt("default") else null
        val enum = p.optJSONArray("enum")
        val type = p.optString("type")
        when {
            enum != null -> {
                val labels = p.optJSONObject("enumLabels")
                out += Prop.Choice(k, title, (0 until enum.length()).map { i -> val v = enum.opt(i).toString(); v to (labels?.optString(v)?.ifEmpty { null } ?: v.replaceFirstChar { it.uppercase() }) })
            }
            p.optString("format") == "color" -> out += Prop.Colour(k, title)
            type == "boolean" -> out += Prop.Bool(k, title)
            (type == "integer" || type == "number") && p.has("minimum") && p.has("maximum") ->
                out += Prop.Num(k, title, p.optDouble("minimum"), p.optDouble("maximum"), type == "integer")
            type == "string" && p.optString("format").isEmpty() -> out += Prop.Text(k, title)
            else -> unsupported = true
        }
    }
    if (unsupported) out += Prop.Text("__studio", "More settings in the studio")
    return out to defaults
}

private fun fmtNum(v: Double, integer: Boolean) = if (integer || v == Math.floor(v)) v.toLong().toString() else String.format("%.2f", v).trimEnd('0').trimEnd('.')

@Composable
fun AppDetailScreen(nav: NavHostController, id: String) {
    val dd = LocalDd.current
    val haptics = LocalHaptics.current
    val toast = LocalToast.current
    val meta by dd.meta.collectAsState()
    val favs by dd.prefs.favourites.collectAsState()
    LaunchedEffect(Unit) { dd.loadMeta() }
    val app = meta?.app(id)
    val scope = rememberCoroutineScope()
    val (props, defaults) = remember(app) { parseProps(app?.schema) }
    val values = remember(app) { mutableStateMapOf<String, Any?>().apply { putAll(defaults) } }
    val pending = remember { HashMap<String, Any?>() }
    var flush by remember { mutableStateOf<Job?>(null) }
    val reset = rememberConfirm()

    fun set(key: String, v: Any?) {
        values[key] = v
        pending[key] = v
        flush?.cancel()
        flush = dd.scope.launch {
            delay(300)
            val body = JSONObject()
            pending.forEach { (k, x) -> body.put(k, x ?: JSONObject.NULL) }
            pending.clear()
            dd.engine.patch("/api/apps/$id/settings", body)
        }
    }

    var textKey by remember { mutableStateOf("") }
    val textInput = rememberTextInput("Value") { set(textKey, it) }
    val state = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(state, focus) {
            if (app == null) {
                item("w") { HeaderItem(it, "App") }
                item("s") { StatusLineItem(it, engineWaitText(), Neutral.onSurfaceVariant) }
                return@SuiteList
            }
            item("h") { HeaderItem(it, app.name) }
            if (app.description.isNotBlank()) item("d") { TextBlockItem(it, app.description, maxLines = 3) }
            if (!app.supported) item("ns") { StatusLineItem(it, "Not on this watch", Neutral.onSurfaceVariant) }
            item("show") {
                GlassPillItem(it, "Show now", accent = true, enabled = app.supported) {
                    scope.launch {
                        if (dd.engine.post("/api/apps/$id/activate") != null) {
                            haptics.confirm()
                            toast.show("On panel")
                        } else {
                            haptics.reject()
                            toast.show("Engine not reachable")
                        }
                    }
                }
            }
            item("pl") {
                GlassPillItem(it, "Add to playlist", w = 300, enabled = app.supported) {
                    scope.launch {
                        val pl = dd.engine.get("/api/playlist")
                        if (pl == null) {
                            haptics.reject(); toast.show("Engine not reachable"); return@launch
                        }
                        val items = pl.optJSONArray("items") ?: org.json.JSONArray()
                        items.put(JSONObject().put("app", id).put("duration", 30).put("enabled", true))
                        val ok = dd.engine.put("/api/playlist", JSONObject().put("enabled", pl.optBoolean("enabled")).put("items", items)) != null
                        if (ok) { haptics.confirm(); toast.show("Added") } else { haptics.reject(); toast.show("Couldn't add") }
                    }
                }
            }
            item("fav") {
                val on = id in favs
                SettingItem(it, Icons.star, "Favourite", null, if (on) Trailing.SwitchOn else Trailing.SwitchOff, onClick = {
                    if (dd.prefs.toggleFavourite(id)) haptics.confirm() else { haptics.reject(); toast.show("Favourites full") }
                })
            }
            app.actions.forEach { a ->
                item("a_${a.id}") {
                    GlassPillItem(it, a.label.ifEmpty { a.id }) {
                        scope.launch {
                            val ok = dd.engine.post("/api/apps/$id/actions/${a.id}") != null
                            if (ok) haptics.confirm() else haptics.reject()
                        }
                    }
                }
            }
            props.forEach { p ->
                item("p_${p.key}") { m ->
                    PropRow(m, p, values[p.key], nav, meta, onSet = { v -> set(p.key, v) }, onText = { textKey = p.key; textInput() })
                }
            }
            if (props.any { it.key != "__studio" }) {
                item("reset") {
                    GlassPillItem(it, if (reset.armed) "Sure?" else "Reset to defaults", error = reset.armed, w = 300) {
                        reset.tap(scope) {
                            defaults.forEach { (k, v) -> values[k] = v }
                            val body = JSONObject()
                            defaults.forEach { (k, v) -> body.put(k, v ?: JSONObject.NULL) }
                            scope.launch { dd.engine.patch("/api/apps/$id/settings", body) }
                            haptics.confirm()
                            toast.show("Reset")
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PropRow(modifier: Modifier, p: Prop, v: Any?, nav: NavHostController, meta: Meta?, onSet: (Any?) -> Unit, onText: () -> Unit) {
    val look = LocalLook.current
    when (p) {
        is Prop.Bool -> {
            val on = v == true
            SettingItem(modifier, Icons.check, p.title, null, if (on) Trailing.SwitchOn else Trailing.SwitchOff, onClick = { onSet(!on) })
        }
        is Prop.Choice -> {
            val cur = v?.toString()
            SettingItem(modifier, Icons.viewList, p.title, p.options.firstOrNull { it.first == cur }?.second ?: cur, Trailing.Chevron, onClick = {
                Pick.choice(nav, ChoiceReq(p.title, p.options, cur) { onSet(it) })
            })
        }
        is Prop.Num -> {
            val d = (v as? Number)?.toDouble() ?: p.min
            SettingItem(modifier, Icons.speed, p.title, fmtNum(d, p.integer), Trailing.Chevron, onClick = {
                val step = if (p.integer) 1.0 else (p.max - p.min) / 50.0
                Pick.number(nav, NumberReq(p.title, d, p.min, p.max, Pick.linear(step, p.min, p.max), { fmtNum(it, p.integer) }) { x ->
                    onSet(if (p.integer) x.roundToInt() else x)
                })
            })
        }
        is Prop.Colour -> {
            val hex = v?.toString()
            val c = runCatching { Color(android.graphics.Color.parseColor(hex)) }.getOrNull()
            SettingItem(modifier, Icons.palette, p.title, hex, Trailing.Swatch, swatch = c ?: look.roles.accent, onClick = {
                Pick.color(nav, ColorReq(p.title, meta?.palette.orEmpty(), hex) { onSet(it) })
            })
        }
        is Prop.Text -> if (p.key == "__studio") {
            SettingItem(modifier, Icons.openNew, p.title, null, Trailing.Chevron, onClick = { nav.navigate(Route.STUDIO) })
        } else {
            SettingItem(modifier, Icons.keyboard, p.title, v?.toString()?.takeIf { it.isNotEmpty() && it != "null" } ?: "Not set", Trailing.Chevron, onClick = onText)
        }
    }
}

