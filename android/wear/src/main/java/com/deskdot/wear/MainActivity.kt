package com.deskdot.wear

import android.graphics.BitmapFactory
import android.os.Bundle
import android.view.HapticFeedbackConstants
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
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
import com.deskdot.wear.theme.WatchPalette
import com.deskdot.wear.theme.WatchThemes
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * DeskDot on the watch: a light remote of the phone (android/wear/SPEC.md). Home shows what's on the panel,
 * brightness, presets and the apps grouped by kind; a kind opens its apps. Every list is Orbit's bubbly glass
 * list. The table theme follows the phone; it's always dark (OLED black, accent on rims), and in ambient it's
 * a dim, still line of text updated once a minute.
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

private fun kindName(c: String) = when (c) {
    "" -> "Other"
    "data" -> "Info"
    else -> c.replaceFirstChar { it.uppercase() }
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

    val palette = WatchThemes.get(summary?.theme).palette(true)

    // Asks the phone only while the screen is awake and visible; the panel preview only on Home.
    LaunchedEffect(lifecycle, ambient, screen, retry) {
        if (ambient) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                runCatching { link.summary() }
                    .onSuccess { summary = it; problem = null }
                    .onFailure { problem = it.message ?: "Can't reach your phone." }
                if (problem == null && apps.isEmpty()) runCatching { apps = link.apps() }
                if (problem == null && screen == Screen.Home) {
                    runCatching { link.frame() }.getOrNull()?.takeIf { it.isNotEmpty() }?.let { b ->
                        BitmapFactory.decodeByteArray(b, 0, b.size)?.let { frame = it.asImageBitmap() }
                    }
                }
                delay(if (screen == Screen.Home) 2000 else 5000)
            }
        }
    }
    // In ambient: one refresh a minute, on the system's signal.
    LaunchedEffect(ambient, tick) { if (ambient) runCatching { link.summary() }.onSuccess { summary = it } }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (ambient) {
            AmbientView(summary)
            return@Box
        }
        val p = problem
        if (p != null && summary == null) {
            Message(p, palette) { retry++ }
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
                Screen.Home -> Home(summary, frame, apps, palette,
                    onBright = { v -> scope.launch { runCatching { link.brightness(v) }; buzz(); summary = summary?.copy(brightness = v) } },
                    onPresets = { scope.launch { runCatching { presets = link.presets() } }; screen = Screen.Presets },
                    onKind = { screen = Screen.Kind(it) },
                )
                is Screen.Kind -> {
                    val list = apps.filter { it.category == s.category }.sortedBy { it.name.lowercase() }
                    PickList(kindName(s.category), list.map { it.name }, palette) { i ->
                        buzz()
                        scope.launch { runCatching { link.activate(list[i].id) } }
                        screen = Screen.Home
                    }
                }
                Screen.Presets -> PickList("Presets", presets.map { it.name }, palette) { i ->
                    buzz()
                    scope.launch { runCatching { link.playPreset(presets[i].id) } }
                    screen = Screen.Home
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
    palette: WatchPalette,
    onBright: (Int) -> Unit,
    onPresets: () -> Unit,
    onKind: (String) -> Unit,
) {
    val kinds = apps.map { it.category }.distinct().sortedBy { KindOrder.indexOf(it).let { i -> if (i < 0) 99 else i } }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    // 0 preview, 1 brightness, 2 presets, then one row per kind of app.
    BubbleList(count = 3 + kinds.size, palette = palette, focus = focus, firstHeight = 132.dp, noBubble = setOf(0)) { i ->
        when (i) {
            0 -> Preview(s, frame, palette)
            1 -> BrightnessRow(s?.brightness ?: 0, palette, onBright)
            2 -> Row("Presets", "One-tap playlists", palette, onPresets)
            else -> {
                val k = kinds[i - 3]
                val n = apps.count { it.category == k }
                Row(kindName(k), if (n == 1) "1 app" else "$n apps", palette) { onKind(k) }
            }
        }
    }
}

/** Exactly what the panel shows, pixel for pixel, in a felt-and-accent glass frame, with its name under it. */
@Composable
private fun Preview(s: Summary?, frame: ImageBitmap?, palette: WatchPalette) {
    Column(Modifier.fillMaxWidth().height(132.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Box(
            Modifier
                .size(92.dp)
                .drawBehind {
                    val r = CornerRadius(14.dp.toPx())
                    drawRoundRect(Color(palette.felt), cornerRadius = r, style = Stroke(6.dp.toPx()))
                    drawRoundRect(Color(palette.accent), Offset(-3f, -3f), Size(size.width + 6f, size.height + 6f), CornerRadius(r.x + 3f), style = Stroke(1.5f))
                }
                .padding(5.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(Color(0xFF050505)),
            contentAlignment = Alignment.Center,
        ) {
            if (frame != null) {
                Image(frame, contentDescription = "The panel", modifier = Modifier.fillMaxSize(), filterQuality = FilterQuality.None)
            }
        }
        Spacer(Modifier.height(8.dp))
        BasicText(
            s?.name?.ifEmpty { "Nothing on" } ?: "…",
            style = TextStyle(Color(palette.ink1), 15.sp, FontWeight.SemiBold, textAlign = TextAlign.Center),
            maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.width(150.dp),
        )
        val status = when {
            s == null -> ""
            s.connected -> "On the panel"
            else -> "Panel not connected"
        }
        BasicText(status, style = TextStyle(Color(if (s?.connected == false) 0xFFFFC24A.toInt() else palette.ink3), 11.sp, textAlign = TextAlign.Center))
    }
}

@Composable
private fun Row(title: String, sub: String?, palette: WatchPalette, onClick: () -> Unit) {
    Column(
        Modifier.fillMaxWidth().height(52.dp).clickable(onClick = onClick).padding(horizontal = 30.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        BasicText(title, style = TextStyle(Color(palette.ink1), 16.sp, FontWeight.SemiBold, textAlign = TextAlign.Center), maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (sub != null) BasicText(sub, style = TextStyle(Color(palette.ink3), 11.sp, textAlign = TextAlign.Center), maxLines = 1)
    }
}

/** − 60 % + : 10 % steps, the panel's 5–100 range. */
@Composable
private fun BrightnessRow(value: Int, palette: WatchPalette, set: (Int) -> Unit) {
    Row(Modifier.fillMaxWidth().height(52.dp), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        RoundKey("−", palette) { set((value - 10).coerceAtLeast(5)) }
        Column(Modifier.width(76.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            BasicText("$value%", style = TextStyle(Color(palette.ink1), 16.sp, FontWeight.SemiBold))
            BasicText("Brightness", style = TextStyle(Color(palette.ink3), 10.sp))
        }
        RoundKey("+", palette) { set((value + 10).coerceAtMost(100)) }
    }
}

@Composable
private fun RoundKey(label: String, palette: WatchPalette, onClick: () -> Unit) {
    Box(
        Modifier
            .size(34.dp)
            .clip(CircleShape)
            .background(Color(palette.chassis2))
            .drawBehind { drawCircle(Color(palette.accentLine), size.minDimension / 2f - 1f, style = Stroke(1.5f)) }
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { BasicText(label, style = TextStyle(Color(palette.accent), 18.sp, FontWeight.Bold)) }
}

@Composable
internal fun PickList(title: String, names: List<String>, palette: WatchPalette, onPick: (Int) -> Unit) {
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    BubbleList(count = names.size + 1, palette = palette, focus = focus, noBubble = setOf(0)) { i ->
        if (i == 0) {
            Box(Modifier.fillMaxWidth().height(52.dp), contentAlignment = Alignment.Center) {
                BasicText(title, style = TextStyle(Color(palette.accent), 13.sp, FontWeight.SemiBold, letterSpacing = 1.sp))
            }
        } else {
            Row(names[i - 1], null, palette) { onPick(i - 1) }
        }
    }
}

@Composable
private fun Message(text: String, palette: WatchPalette, onRetry: () -> Unit) {
    Column(Modifier.fillMaxSize().padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        BasicText("DeskDot", style = TextStyle(Color(palette.accent), 14.sp, FontWeight.SemiBold))
        Spacer(Modifier.height(10.dp))
        BasicText(text, style = TextStyle(Color(palette.ink1), 15.sp, textAlign = TextAlign.Center))
        Spacer(Modifier.height(14.dp))
        RoundKey("↻", palette, onRetry)
    }
}

/** Ambient: black, one dim still line of what's on, no frame, no glass; once a minute. */
@Composable
internal fun AmbientView(s: Summary?) {
    Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        BasicText("DeskDot", style = TextStyle(Color(0xFF8A8A8A), 12.sp))
        Spacer(Modifier.height(6.dp))
        BasicText(s?.name?.ifEmpty { "Nothing on" } ?: "", style = TextStyle(Color(0xFFD0D0D0), 18.sp, textAlign = TextAlign.Center), maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.width(160.dp))
    }
}
