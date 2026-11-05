package com.deskdot.wear

import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.HapticFeedbackConstants
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.wear.ambient.AmbientLifecycleObserver
import androidx.wear.compose.foundation.BasicSwipeToDismissBox
import androidx.wear.compose.foundation.rememberSwipeToDismissBoxState
import com.deskdot.wear.design.GlassButton
import com.deskdot.wear.design.GlassFactory
import com.deskdot.wear.design.GlassRow
import com.deskdot.wear.design.GlassVariant
import com.deskdot.wear.design.Icons
import com.deskdot.wear.design.LocalLook
import com.deskdot.wear.design.Look
import com.deskdot.wear.design.RowSlot
import com.deskdot.wear.design.drawGlass
import com.deskdot.wear.design.drawIcon
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.abs

/**
 * DeskDot on the watch: a light remote of the phone (android/wear/SPEC.md). Home shows what's on the panel with
 * ‹ › to step to the previous / next app, brightness, presets and the apps grouped by kind; a kind opens its apps.
 * It wears Orbit's look: glass pills with an icon per kind, jelly glass buttons, the table's accent and felt on the
 * rims, OLED black. The table follows the phone; in ambient it's a dim LED-dot sleep face updated once a minute.
 */
class MainActivity : ComponentActivity() {
    private val ambient = mutableStateOf(false)
    private val tick = mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lifecycle.addObserver(
            AmbientLifecycleObserver(
                this,
                object : AmbientLifecycleObserver.AmbientLifecycleCallback {
                    override fun onEnterAmbient(ambientDetails: AmbientLifecycleObserver.AmbientDetails) { ambient.value = true }
                    override fun onExitAmbient() { ambient.value = false }
                    override fun onUpdateAmbient() { tick.intValue++ }
                },
            ),
        )
        val link = PhoneLink(applicationContext)
        setContent { DeskDotWatch(link, ambient.value, tick.intValue) }
    }
}

private sealed interface Screen {
    data object Home : Screen
    data class Kind(val category: String) : Screen
    data object Presets : Screen
}

/** Kinds in the studio's order; anything new goes after them. */
private val KindOrder = listOf("games", "casino", "pets", "time", "data", "media", "creative", "ambient", "productivity")

private fun kindRank(c: String) = KindOrder.indexOf(c).let { if (it < 0) 99 else it }

private fun kindName(c: String) = when (c) {
    "" -> "Other"
    "data" -> "Info"
    else -> c.replaceFirstChar { it.uppercase() }
}

/** Every app in the order the watch lists them: kinds in the studio's order, then by name within a kind. */
internal fun watchOrder(apps: List<AppItem>): List<AppItem> =
    apps.sortedWith(compareBy<AppItem>({ kindRank(it.category) }, { it.category }, { it.name.lowercase() }))

/**
 * The app to show after [current] when stepping [dir] (+1 next, -1 previous) through [watchOrder], wrapping at the
 * ends. With nothing (or an unknown app) on the panel, next starts at the first app and previous at the last.
 */
internal fun neighbour(apps: List<AppItem>, current: String, dir: Int): AppItem? {
    val list = watchOrder(apps)
    if (list.isEmpty()) return null
    val i = list.indexOfFirst { it.id == current }
    if (i < 0) return if (dir >= 0) list.first() else list.last()
    return list[Math.floorMod(i + dir, list.size)]
}

/** The name to show: the phone's, else the app's own name from the list, else "Nothing on". */
internal fun shownName(s: Summary?, apps: List<AppItem>): String = when {
    s == null -> "…"
    s.name.isNotEmpty() && s.name != s.current -> s.name
    s.current.isEmpty() -> "Nothing on"
    else -> apps.firstOrNull { it.id == s.current }?.name ?: s.name.ifEmpty { s.current }
}

@Composable
fun DeskDotWatch(link: PhoneLink, ambient: Boolean, tick: Int) {
    var summary by remember { mutableStateOf<Summary?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }
    var apps by remember { mutableStateOf<List<AppItem>>(emptyList()) }
    var presets by remember { mutableStateOf<List<PresetItem>>(emptyList()) }
    var frame by remember { mutableStateOf<ImageBitmap?>(null) }
    var screen by remember { mutableStateOf<Screen>(Screen.Home) }
    var retry by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    val lifecycle = LocalLifecycleOwner.current
    val view = LocalView.current
    fun buzz() = view.performHapticFeedback(HapticFeedbackConstants.CONFIRM)
    suspend fun refreshFrame() {
        runCatching { link.frame() }.getOrNull()?.takeIf { it.isNotEmpty() }?.let { b ->
            BitmapFactory.decodeByteArray(b, 0, b.size)?.let { frame = it.asImageBitmap() }
        }
    }

    val look = remember(summary?.theme) { Look(summary?.theme?.ifEmpty { null } ?: com.deskdot.wear.theme.WatchThemes.DEFAULT, dark = true) }

    // Asks the phone only while the screen is awake and visible; the panel preview only on Home.
    LaunchedEffect(lifecycle, ambient, screen, retry) {
        if (ambient) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                runCatching { link.summary() }
                    .onSuccess { summary = it; problem = null }
                    .onFailure { problem = it.message ?: "Can't reach your phone." }
                if (problem == null && apps.isEmpty()) runCatching { apps = link.apps() }
                if (problem == null && screen == Screen.Home) refreshFrame()
                delay(if (screen == Screen.Home) 2000 else 5000)
            }
        }
    }
    // In ambient: one refresh a minute, on the system's signal (the name and the panel's picture).
    LaunchedEffect(ambient, tick) {
        if (!ambient) return@LaunchedEffect
        runCatching { link.summary() }.onSuccess { summary = it }
        refreshFrame()
    }

    fun show(app: AppItem) {
        buzz()
        summary = summary?.copy(current = app.id, name = app.name)
        scope.launch {
            runCatching { link.activate(app.id) }
            refreshFrame()
        }
    }

    CompositionLocalProvider(LocalLook provides look) {
        Box(Modifier.fillMaxSize().background(if (ambient) Color.Black else look.bg)) {
            if (ambient) {
                AmbientView(summary?.copy(name = shownName(summary, apps)), frame, tick)
                return@Box
            }
            val p = problem
            if (p != null && summary == null) {
                Message(p) { retry++ }
                return@Box
            }
            val box = rememberSwipeToDismissBoxState()
            BasicSwipeToDismissBox(
                onDismissed = { screen = Screen.Home },
                state = box,
                backgroundKey = screen,
                contentKey = screen,
                userSwipeEnabled = screen != Screen.Home,
            ) { isBackground ->
                if (isBackground && screen != Screen.Home) return@BasicSwipeToDismissBox
                when (val s = if (isBackground) Screen.Home else screen) {
                    Screen.Home -> Home(summary, frame, apps,
                        onStep = { dir -> neighbour(apps, summary?.current.orEmpty(), dir)?.let { show(it) } },
                        onBright = { v -> scope.launch { runCatching { link.brightness(v) }; buzz(); summary = summary?.copy(brightness = v) } },
                        onPresets = { scope.launch { runCatching { presets = link.presets() } }; screen = Screen.Presets },
                        onKind = { screen = Screen.Kind(it) },
                    )
                    is Screen.Kind -> {
                        val list = watchOrder(apps.filter { it.category == s.category })
                        PickList(kindName(s.category), Icons.forKind(s.category), list.map { it.name },
                            on = list.indexOfFirst { it.id == summary?.current }) { i ->
                            show(list[i])
                            screen = Screen.Home
                        }
                    }
                    Screen.Presets -> PickList("Presets", Icons.playlist, presets.map { it.name }, on = -1) { i ->
                        buzz()
                        scope.launch { runCatching { link.playPreset(presets[i].id) } }
                        screen = Screen.Home
                    }
                }
            }
        }
    }
}

@Composable
internal fun Home(
    s: Summary?,
    frame: ImageBitmap?,
    apps: List<AppItem>,
    onStep: (Int) -> Unit,
    onBright: (Int) -> Unit,
    onPresets: () -> Unit,
    onKind: (String) -> Unit,
) {
    val kinds = apps.map { it.category }.distinct().sortedBy { kindRank(it) }
    // 0 preview, 1 brightness, 2 presets, then one row per kind of app.
    BubbleList(count = 3 + kinds.size, firstHeight = PreviewH, noBubble = setOf(0, 1)) { i ->
        when (i) {
            0 -> Preview(s, frame, shownName(s, apps), canStep = apps.size > 1, onStep)
            1 -> BrightnessRow(s?.brightness ?: 0, onBright)
            2 -> GlassRow(Icons.playlist, "Presets", "One-tap playlists", onPresets)
            else -> {
                val k = kinds[i - 3]
                val n = apps.count { it.category == k }
                GlassRow(Icons.forKind(k), kindName(k), if (n == 1) "1 app" else "$n apps") { onKind(k) }
            }
        }
    }
}

private val PreviewH = 150.dp
private val FrameSize = 100.dp

/**
 * Exactly what the panel shows, pixel for pixel, inside Orbit's glass frame (glass only on the border, so nothing
 * covers the picture), with glass ‹ › either side to step to the previous / next app. A sideways swipe on the
 * picture does the same. The app's name and the panel's state sit under it.
 */
@Composable
private fun Preview(s: Summary?, frame: ImageBitmap?, name: String, canStep: Boolean, onStep: (Int) -> Unit) {
    val look = LocalLook.current
    Column(Modifier.fillMaxWidth().height(PreviewH), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (canStep) GlassButton(Icons.back, "Previous app", 36.dp, { onStep(-1) })
            Spacer(Modifier.width(8.dp))
            Box(
                Modifier
                    .size(FrameSize)
                    .pointerInput(canStep) {
                        if (!canStep) return@pointerInput
                        var dx = 0f
                        detectHorizontalDragGestures(
                            onDragStart = { dx = 0f },
                            onDragEnd = { if (abs(dx) > 48f) onStep(if (dx < 0) 1 else -1) },
                        ) { change, amount -> change.consume(); dx += amount }
                    }
                    .drawWithCache {
                        val w = size.width.toInt()
                        val g = GlassFactory.get(look.glass(w, w, 16.dp.toPx(), GlassVariant.Frame))
                        onDrawWithContent {
                            drawContent()
                            drawGlass(g, 0f, 0f)
                        }
                    }
                    .padding(7.dp)
                    .clip(RoundedCornerShape(9.dp))
                    .background(Color(0xFF050505)),
                contentAlignment = Alignment.Center,
            ) {
                if (frame != null) {
                    Image(frame, contentDescription = "The panel", modifier = Modifier.fillMaxSize(), filterQuality = FilterQuality.None)
                }
            }
            Spacer(Modifier.width(8.dp))
            if (canStep) GlassButton(Icons.next, "Next app", 36.dp, { onStep(1) })
        }
        Spacer(Modifier.height(7.dp))
        BasicText(
            name,
            style = TextStyle(look.ink1, 15.sp, FontWeight.SemiBold, textAlign = TextAlign.Center),
            maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.width(150.dp),
        )
        val status = when {
            s == null -> ""
            s.connected -> "On the panel"
            else -> "Panel not connected"
        }
        BasicText(status, style = TextStyle(if (s?.connected == false) Color(0xFFFFC24A) else look.ink3, 11.sp, textAlign = TextAlign.Center))
    }
}

/** Jelly glass − and + either side of the level: 10 % steps, the panel's 5–100 range. */
@Composable
private fun BrightnessRow(value: Int, set: (Int) -> Unit) {
    val look = LocalLook.current
    Row(Modifier.fillMaxWidth().height(RowSlot), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        GlassButton(Icons.remove, "Dimmer", 42.dp, { set((value - 10).coerceAtLeast(5)) })
        Column(Modifier.width(84.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Box(
                Modifier.size(18.dp).drawWithCache {
                    onDrawBehind { drawIcon(Icons.sun, size.width / 2f, size.height / 2f, size.width, look.accent) }
                },
            )
            BasicText("$value%", style = TextStyle(look.ink1, 17.sp, FontWeight.SemiBold))
        }
        GlassButton(Icons.add, "Brighter", 42.dp, { set((value + 10).coerceAtMost(100)) })
    }
}

/** A kind's apps (or the presets): a title, then a glass pill per item; [on] marks the one on the panel now. */
@Composable
internal fun PickList(title: String, icon: com.deskdot.wear.design.WIcon, names: List<String>, on: Int = -1, onPick: (Int) -> Unit) {
    val look = LocalLook.current
    BubbleList(count = names.size + 1, noBubble = setOf(0)) { i ->
        if (i == 0) {
            Box(Modifier.fillMaxWidth().height(RowSlot), contentAlignment = Alignment.Center) {
                BasicText(title, style = TextStyle(look.accent, 14.sp, FontWeight.SemiBold, letterSpacing = 1.sp))
            }
        } else {
            GlassRow(icon, names[i - 1], if (i - 1 == on) "On the panel now" else null) { onPick(i - 1) }
        }
    }
}

@Composable
private fun Message(text: String, onRetry: () -> Unit) {
    val look = LocalLook.current
    Column(Modifier.fillMaxSize().padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        BasicText("DeskDot", style = TextStyle(look.accent, 14.sp, FontWeight.SemiBold))
        Spacer(Modifier.height(10.dp))
        BasicText(text, style = TextStyle(look.ink1, 15.sp, textAlign = TextAlign.Center))
        Spacer(Modifier.height(14.dp))
        GlassButton(Icons.retry, "Try again", 44.dp, onRetry, variant = GlassVariant.On)
    }
}

/**
 * Ambient: the sleep face. The panel's picture redrawn as dim LED dots (so every app gets its own sleep look:
 * the clock, a game, the weather...), the time of day above it and the app's name below, in grey. Redrawn once a
 * minute; the whole face drifts a few px each minute against burn-in. Lit pixels stay well under 15 %.
 */
@Composable
internal fun AmbientView(s: Summary?, frame: ImageBitmap?, tick: Int = 0) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val dots = remember(frame) { frame?.let { ledDots(it) } }
    val now = remember(tick) { java.util.Date() }
    val time = remember(tick) { android.text.format.DateFormat.getTimeFormat(context).format(now) }
    val dx = ((tick % 5) - 2) * 2
    val dy = (((tick / 5) % 5) - 2) * 2
    Column(
        Modifier.fillMaxSize().padding(start = (dx + 4).coerceAtLeast(0).dp, top = (dy + 4).coerceAtLeast(0).dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        BasicText(time, style = TextStyle(Color(0xFFB0B0B0), 22.sp, textAlign = TextAlign.Center))
        Spacer(Modifier.height(8.dp))
        Box(
            Modifier.size(104.dp).drawWithCache {
                onDrawBehind {
                    val px = dots ?: return@onDrawBehind
                    val cell = size.width / 32f
                    for (y in 0 until 32) for (x in 0 until 32) {
                        val c = px[y * 32 + x]
                        if (c == 0) continue
                        drawCircle(Color(c), cell * 0.32f, androidx.compose.ui.geometry.Offset((x + 0.5f) * cell, (y + 0.5f) * cell))
                    }
                }
            },
        )
        Spacer(Modifier.height(8.dp))
        BasicText(
            s?.name?.ifEmpty { "Nothing on" } ?: "DeskDot",
            style = TextStyle(Color(0xFF9A9A9A), 14.sp, textAlign = TextAlign.Center),
            maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.width(150.dp),
        )
    }
}

/**
 * The panel's 32 x 32 picture as dim LED colours for ambient: each LED sampled from its cell, darkened to ~45 % and
 * dropped when nearly black, so the sleep face lights only the dots the app lights. 0 = off.
 */
private fun ledDots(img: ImageBitmap): IntArray {
    val bmp = img.asAndroidBitmap()
    val out = IntArray(32 * 32)
    val sx = bmp.width / 32f
    val sy = bmp.height / 32f
    for (y in 0 until 32) for (x in 0 until 32) {
        val c = bmp.getPixel(((x + 0.5f) * sx).toInt().coerceAtMost(bmp.width - 1), ((y + 0.5f) * sy).toInt().coerceAtMost(bmp.height - 1))
        val r = (c shr 16) and 255
        val g = (c shr 8) and 255
        val b = c and 255
        if (r + g + b < 60) continue
        val k = 0.45f
        out[y * 32 + x] = (0xFF shl 24) or ((r * k).toInt() shl 16) or ((g * k).toInt() shl 8) or (b * k).toInt()
    }
    return out
}
