package com.deskdot.app.wear

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.foundation.pager.PagerState
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.wear.compose.material.HorizontalPageIndicator
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.PageIndicatorState
import androidx.wear.compose.navigation.SwipeDismissableNavHost
import androidx.wear.compose.navigation.composable
import androidx.wear.compose.navigation.rememberSwipeDismissableNavController
import com.deskdot.app.wear.net.EngineClient
import com.deskdot.app.wear.screens.AppDetailScreen
import com.deskdot.app.wear.screens.AppsScreen
import com.deskdot.app.wear.screens.DisplayScreen
import com.deskdot.app.wear.screens.EngineScreen
import com.deskdot.app.wear.screens.GamepadScreen
import com.deskdot.app.wear.screens.GameSetupScreen
import com.deskdot.app.wear.screens.GamesScreen
import com.deskdot.app.wear.screens.LobbyScreen
import com.deskdot.app.wear.screens.MoreScreen
import com.deskdot.app.wear.screens.NowPlayingScreen
import com.deskdot.app.wear.screens.OnboardingScreen
import com.deskdot.app.wear.screens.PanelScreen
import com.deskdot.app.wear.screens.PlaylistsScreen
import com.deskdot.app.wear.screens.SettingsScreen
import com.deskdot.app.wear.screens.StudioScreen

/** Route names for the NavHost (androidx.wear.compose.navigation). */
object Routes {
    const val HOME = "home"
    const val ONBOARDING = "onboarding"
    const val PANEL = "panel"
    const val APP_DETAIL = "app/{id}"
    const val GAME_SETUP = "game/{id}"
    const val LOBBY = "lobby/{app}"
    const val GAMEPAD = "gamepad/{id}"
    const val DISPLAY = "display"
    const val ENGINE = "engine"
    const val STUDIO = "studio"
    const val SETTINGS = "settings"

    fun appDetail(id: String) = "app/$id"
    fun gameSetup(id: String) = "game/$id"
    fun lobby(app: String) = "lobby/$app"
    fun gamepad(id: String) = "gamepad/$id"
}

/**
 * Root composable: one [EngineClient] shared by the whole app (it owns the single `/ws` connection, opened and
 * closed from each screen's lifecycle so the socket only exists while something is on screen — see
 * EngineClient.connect/disconnect and each screen's DisposableEffect).
 *
 * First run (no paired panel) goes to onboarding (§5.2a); otherwise the root is the 5-page HorizontalPager
 * (§5.1). The pairing check is a single `GET /api/state` — the engine itself decides what "paired" means
 * (`state.device.address != null`); the watch UI never maintains its own copy of that fact.
 */
@Composable
fun WearApp(engine: EngineClient) {
    var checkedPairing by remember { mutableStateOf(false) }
    var isPaired by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        // The Chaquopy engine thread (EngineService) takes a few seconds to bind :8765 after process start, so
        // this retries briefly instead of taking "connection refused" as "no panel paired" on a cold launch.
        var state: org.json.JSONObject? = null
        var attempts = 0
        while (state == null && attempts < 15) {
            state = engine.get("/api/state").takeIf { it.length() > 0 }
            if (state == null) kotlinx.coroutines.delay(500)
            attempts++
        }
        val device = state?.optJSONObject("device")
        isPaired = device?.optString("address", "").orEmpty().isNotEmpty() && device?.optString("status") != "error"
        checkedPairing = true
    }

    if (!checkedPairing) return // a blank black frame for one frame; cheaper than a spinner on first composition

    MaterialTheme {
        val nav = rememberSwipeDismissableNavController()
        SwipeDismissableNavHost(
            navController = nav,
            startDestination = if (isPaired) Routes.HOME else Routes.ONBOARDING,
        ) {
            composable(Routes.ONBOARDING) {
                OnboardingScreen(engine) { nav.navigate(Routes.HOME) { popUpTo(0) } }
            }
            composable(Routes.HOME) { HomePager(engine, nav) }
            composable(Routes.PANEL) { PanelScreen(engine, nav) }
            composable(Routes.APP_DETAIL) { backStackEntry ->
                val id = backStackEntry.arguments?.getString("id") ?: return@composable
                AppDetailScreen(engine, id, nav)
            }
            composable(Routes.GAME_SETUP) { backStackEntry ->
                val id = backStackEntry.arguments?.getString("id") ?: return@composable
                GameSetupScreen(engine, id, nav)
            }
            composable(Routes.LOBBY) { backStackEntry ->
                val app = backStackEntry.arguments?.getString("app") ?: return@composable
                LobbyScreen(engine, app, nav)
            }
            composable(Routes.GAMEPAD) { backStackEntry ->
                val id = backStackEntry.arguments?.getString("id") ?: return@composable
                GamepadScreen(engine, id)
            }
            composable(Routes.DISPLAY) { DisplayScreen(engine) }
            composable(Routes.ENGINE) { EngineScreen(engine) }
            composable(Routes.STUDIO) { StudioScreen(engine) }
            composable(Routes.SETTINGS) { SettingsScreen(engine) }
        }
    }
}

/** DESIGN_SPEC §5.1: the 5-page root pager (Now Playing / Apps / Games / Playlists / More), with the Orbit page
 * indicator (5 dots). Swiping right on page 0 exits the UI (handled by the Activity's edge-swipe / back). */
@Composable
private fun HomePager(engine: EngineClient, nav: NavHostController) {
    val pagerState = rememberPagerState(initialPage = 0) { 5 }
    Box(Modifier.fillMaxSize()) {
        HorizontalPager(state = pagerState, modifier = Modifier.fillMaxSize()) { page ->
            when (page) {
                0 -> NowPlayingScreen(engine, nav)
                1 -> AppsScreen(engine, nav)
                2 -> GamesScreen(engine, nav)
                3 -> PlaylistsScreen(engine)
                4 -> MoreScreen(engine, nav)
            }
        }
        HorizontalPageIndicator(pageIndicatorState = remember(pagerState) { PagerPageIndicatorState(pagerState) })
    }
}

/** Adapts Compose's [PagerState] to Wear Material's [PageIndicatorState] for the 5-dot page indicator
 * (DESIGN_SPEC §5.1 / §4.3). */
private class PagerPageIndicatorState(private val pagerState: PagerState) : PageIndicatorState {
    override val pageOffset: Float
        get() = pagerState.currentPageOffsetFraction
    override val selectedPage: Int
        get() = pagerState.currentPage
    override val pageCount: Int
        get() = pagerState.pageCount
}
