package com.deskdot.app.wear.screens

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.navArgument
import androidx.wear.compose.navigation.SwipeDismissableNavHost
import androidx.wear.compose.navigation.composable
import androidx.wear.compose.navigation.rememberSwipeDismissableNavController
import com.deskdot.app.wear.Dd
import com.deskdot.app.wear.data.SuiteSignalSource
import com.deskdot.app.wear.data.SuiteSignals
import com.deskdot.app.wear.design.AccentThemes
import com.deskdot.app.wear.design.LocalHaptics
import com.deskdot.app.wear.design.MotionPolicy
import com.deskdot.app.wear.design.SuiteHaptics
import com.deskdot.app.wear.design.SuiteLook
import com.deskdot.app.wear.design.SuiteMode
import com.deskdot.app.wear.design.SuiteTheme
import com.deskdot.app.wear.design.SuiteToast
import com.deskdot.app.wear.design.ToastState
import com.deskdot.app.wear.nav.Route
import com.deskdot.app.wear.ui.LocalDd
import com.deskdot.app.wear.ui.LocalToast
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Hardware keys and launch requests the activity forwards into Compose (pushers I-13, Ongoing Activity tap). */
object Signals {
    val keys = MutableSharedFlow<Int>(extraBufferCapacity = 4)
    val open = MutableSharedFlow<String>(replay = 1, extraBufferCapacity = 1)
}

/**
 * Root of DeskDot Watch: the suite look (Orbit's theme or the local fallback), haptics, the toast, and the
 * swipe-dismissable navigation graph. First run starts at Welcome (§5.2a); afterwards at the 5-page pager (§5.1).
 */
@Composable
fun WearRoot(dd: Dd, needPermissions: Boolean) {
    val signals = rememberSuiteSignals(dd)
    val reducedMotion = remember {
        runCatching { Settings.Global.getFloat(dd.context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }.getOrDefault(false)
    }
    val look = remember(signals.accent, signals.lowEnergy, signals.calm, reducedMotion) {
        SuiteLook(
            mode = if (signals.lowEnergy) SuiteMode.LowEnergy else SuiteMode.Wake,
            roles = AccentThemes.of(signals.accent),
            calm = signals.calm,
            motion = MotionPolicy(cut = signals.lowEnergy || reducedMotion, calm = signals.calm),
        )
    }
    val view = LocalView.current
    val hapticLevel by dd.prefs.haptics.collectAsState()
    val haptics = remember(view) { SuiteHaptics(view) }
    haptics.level = dd.prefs.hapticsLevel()
    haptics.crownTicks = signals.crownTicks
    @Suppress("UNUSED_EXPRESSION") hapticLevel

    val toast = remember { ToastState() }

    // Engine start-up and the things that need it once: adopt a panel paired earlier, adopt a running lobby.
    LaunchedEffect(Unit) {
        if (dd.engine.awaitReady()) {
            val st = dd.engine.refreshState()
            if (st?.device?.address != null && !dd.prefs.onboarded.value) dd.prefs.setOnboarded(true)
            dd.loadMeta()
            dd.hosting.resync()
        }
    }

    // The watch-face complication shows the panel status: ask faces to refresh when it changes (no polling).
    LaunchedEffect(Unit) {
        var last: String? = null
        dd.engine.state.collect { st ->
            val k = st?.device?.status
            if (k != null && k != last) {
                last = k
                com.deskdot.app.wear.complication.ComplicationPush.request(dd.context)
            }
        }
    }

    // I-20: Thermal Calm caps the engine at 10 fps and restores the user's value afterwards.
    LaunchedEffect(signals.calm) {
        if (!dd.engine.awaitReady(10_000)) return@LaunchedEffect
        if (signals.calm) {
            if (dd.calmSavedFps == null) {
                val cur = dd.engine.refreshState()?.maxFps ?: return@LaunchedEffect
                if (cur > 10.0) {
                    dd.calmSavedFps = cur
                    dd.engine.patch("/api/display", JSONObject().put("max_fps", 10))
                }
            }
        } else {
            dd.calmSavedFps?.let { saved ->
                dd.engine.patch("/api/display", JSONObject().put("max_fps", saved))
                dd.calmSavedFps = null
            }
        }
    }

    SuiteTheme(look) {
        CompositionLocalProvider(LocalHaptics provides haptics, LocalDd provides dd, LocalToast provides toast) {
            Box(Modifier.fillMaxSize()) {
                val nav = rememberSwipeDismissableNavController()
                val start = when {
                    !dd.prefs.onboarded.value -> Route.WELCOME
                    needPermissions -> Route.PERMS
                    else -> Route.HOME
                }
                Graph(nav, start)
                LaunchedEffect(nav) {
                    Signals.open.collect { what ->
                        if (what == "lobby" && dd.prefs.onboarded.value) {
                            runCatching { nav.navigate(Route.LOBBY) { launchSingleTop = true } }
                        }
                    }
                }
                SuiteToast(toast)
            }
        }
    }
}

@Composable
private fun Graph(nav: NavHostController, start: String) {
    SwipeDismissableNavHost(navController = nav, startDestination = start) {
        composable(Route.HOME) { HomePager(nav) }
        composable(Route.WELCOME) { WelcomeScreen(nav) }
        composable(Route.PERMS) { PermissionsScreen(nav) }
        composable(Route.SCAN) { ScanScreen(nav) }
        composable(
            Route.CONNECT,
            arguments = listOf(navArgument("addr") { type = NavType.StringType; defaultValue = "" }, navArgument("name") { type = NavType.StringType; defaultValue = "" }),
        ) { e -> ConnectScreen(nav, e.arguments?.getString("addr").orEmpty(), e.arguments?.getString("name").orEmpty()) }
        composable(Route.FULL) { FullViewScreen() }
        composable(Route.APP_LIST, arguments = listOf(navArgument("cat") { type = NavType.StringType; defaultValue = "" })) { e ->
            AppListScreen(nav, e.arguments?.getString("cat").orEmpty())
        }
        composable(Route.SEARCH, arguments = listOf(navArgument("q") { type = NavType.StringType; defaultValue = "" })) { e ->
            SearchScreen(nav, e.arguments?.getString("q").orEmpty())
        }
        composable(Route.APP) { e -> AppDetailScreen(nav, e.arguments?.getString("id").orEmpty()) }
        composable(Route.GAME) { e -> GameSetupScreen(nav, e.arguments?.getString("id").orEmpty()) }
        composable(Route.LOBBY) { LobbyScreen(nav) }
        composable(Route.GAMEPAD) { e -> GamepadScreen(e.arguments?.getString("id").orEmpty()) }
        composable(Route.CASINO) { CasinoScreen(nav) }
        composable(Route.TV) { TvScreen(nav) }
        composable(Route.PL_ITEM) { e -> PlaylistItemScreen(nav, e.arguments?.getString("id").orEmpty()) }
        composable(Route.PL_NEW) { NewPlaylistScreen(nav) }
        composable(Route.PANEL) { PanelScreen(nav) }
        composable(Route.DISPLAY) { DisplayScreen(nav) }
        composable(Route.ENGINE) { EngineScreen() }
        composable(Route.STUDIO) { StudioScreen() }
        composable(Route.SETTINGS) { SettingsScreen(nav) }
        composable(Route.ACCENT) { AccentScreen() }
        composable(Route.LOW_ENERGY) { LowEnergyScreen(nav) }
        composable(Route.CHOICE) { ChoiceScreen(nav) }
        composable(Route.NUMBER) { NumberScreen() }
        composable(Route.COLOR) { ColorScreen(nav) }
    }
}

/** §5.1: the root HorizontalPager of 5 pages with the 5-dot indicator. Page 0 swipe-right exits (NavHost). */
@Composable
private fun HomePager(nav: NavHostController) {
    val pager = rememberPagerState(initialPage = 0) { 5 }
    Box(Modifier.fillMaxSize()) {
        HorizontalPager(state = pager, modifier = Modifier.fillMaxSize(), beyondViewportPageCount = 0, key = { it }) { page ->
            when (page) {
                0 -> NowPlayingPage(nav, pager)
                1 -> AppsPage(nav, pager)
                2 -> GamesPage(nav, pager)
                3 -> PlaylistsPage(nav, pager)
                else -> MorePage(nav, pager)
            }
        }
        com.deskdot.app.wear.design.SuiteTimeText()
        // The page dots step aside (alpha only, draw phase) while Now Playing's crown brightness arc is up,
        // because that arc runs through the dots' ring (§5.3 arc r 200, 150°–210°).
        com.deskdot.app.wear.design.PageDots(pager, Modifier.graphicsLayer { alpha = PagerChrome.dotsAlpha })
    }
}

/** Pager chrome shared by the pages (read in draw only). */
object PagerChrome {
    var dotsAlpha by androidx.compose.runtime.mutableFloatStateOf(1f)
}

/** True while [page] is the pager's settled page (crown focus goes only to the visible page). */
fun PagerState.active(page: Int) = settledPage == page

/**
 * Reads the suite signals on every resume and while resumed listens for Orbit's change notifications and for
 * battery / Battery Saver broadcasts (§4.1, §2.6). Nothing is registered while the app is not visible.
 */
@Composable
private fun rememberSuiteSignals(dd: Dd): SuiteSignals {
    val ctx = LocalContext.current.applicationContext
    var sig by remember { mutableStateOf(SuiteSignalSource.read(ctx, dd.prefs, SuiteSignals())) }
    val lifecycle = LocalLifecycleOwner.current
    LaunchedEffect(lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            sig = SuiteSignalSource.read(ctx, dd.prefs, sig)
            val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
                override fun onChange(selfChange: Boolean) {
                    sig = SuiteSignalSource.read(ctx, dd.prefs, sig)
                }
            }
            val receiver = object : BroadcastReceiver() {
                override fun onReceive(c: Context?, i: Intent?) {
                    val next = SuiteSignalSource.read(ctx, dd.prefs, sig)
                    if (next != sig) sig = next
                }
            }
            runCatching { ctx.contentResolver.registerContentObserver(SuiteSignalSource.ORBIT_URI, false, observer) }
            ctx.registerReceiver(receiver, IntentFilter().apply {
                addAction(Intent.ACTION_BATTERY_CHANGED)
                addAction(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED)
            })
            val prefsJob = launch {
                combine(dd.prefs.accent, dd.prefs.leMode, dd.prefs.leThreshold, dd.prefs.crownTicks) { _, _, _, _ -> Unit }
                    .collect { sig = SuiteSignalSource.read(ctx, dd.prefs, sig) }
            }
            try {
                awaitCancellation()
            } finally {
                prefsJob.cancel()
                runCatching { ctx.contentResolver.unregisterContentObserver(observer) }
                runCatching { ctx.unregisterReceiver(receiver) }
            }
        }
    }
    return sig
}

/** Shared flow accessor so screens don't import the object directly. */
val hardwareKeys: SharedFlow<Int> get() = Signals.keys
