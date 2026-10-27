package com.deskdot.app.wear

import android.app.Application
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.test.getBoundsInRoot
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeUp
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.navigation.NavHostController
import androidx.test.core.app.ApplicationProvider
import androidx.wear.compose.navigation.rememberSwipeDismissableNavController
import com.deskdot.app.wear.ble.PanelCandidate
import com.deskdot.app.wear.design.AccentId
import com.deskdot.app.wear.design.AccentThemes
import com.deskdot.app.wear.design.HeaderItem
import com.deskdot.app.wear.design.Icons
import com.deskdot.app.wear.design.LocalHaptics
import com.deskdot.app.wear.design.MotionPolicy
import com.deskdot.app.wear.design.PageDots
import com.deskdot.app.wear.design.SettingItem
import com.deskdot.app.wear.design.SuiteFonts
import com.deskdot.app.wear.design.SuiteHaptics
import com.deskdot.app.wear.design.SuiteList
import com.deskdot.app.wear.design.SuiteLook
import com.deskdot.app.wear.design.SuiteMode
import com.deskdot.app.wear.design.SuiteTheme
import com.deskdot.app.wear.design.SuiteTimeText
import com.deskdot.app.wear.design.ToastState
import com.deskdot.app.wear.design.rememberSuiteListState
import com.deskdot.app.wear.screens.AppDetailScreen
import com.deskdot.app.wear.screens.AppsPage
import com.deskdot.app.wear.screens.ConnectScreen
import com.deskdot.app.wear.screens.DisplayScreen
import com.deskdot.app.wear.screens.EngineScreen
import com.deskdot.app.wear.screens.FullViewScreen
import com.deskdot.app.wear.screens.GameSetupScreen
import com.deskdot.app.wear.screens.GamepadScreen
import com.deskdot.app.wear.screens.GamesPage
import com.deskdot.app.wear.screens.LobbyScreen
import com.deskdot.app.wear.screens.MorePage
import com.deskdot.app.wear.screens.NowPlayingPage
import com.deskdot.app.wear.screens.PanelScreen
import com.deskdot.app.wear.screens.PlaylistsPage
import com.deskdot.app.wear.screens.ScanScreen
import com.deskdot.app.wear.screens.SettingsScreen
import com.deskdot.app.wear.screens.StudioScreen
import com.deskdot.app.wear.screens.WelcomeScreen
import com.deskdot.app.wear.screens.scanPreview
import com.deskdot.app.wear.ui.LocalDd
import com.deskdot.app.wear.ui.LocalToast
import com.github.takahirom.roborazzi.captureRoboImage
import kotlinx.coroutines.runBlocking
import org.junit.AfterClass
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.BeforeClass
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * Every DeskDot Watch screen rendered at 416 x 416 (density 320: 208 x 208 dp, round) against [FakeEngine] — the
 * production EngineClient over real HTTP — captured next to the design-preview numbering (29_…50_). Output:
 * android/app/build/outputs/roborazzi/. Plus the §4.2.8 R1 bounds test for the shared list.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [33], qualifiers = WEAR_QUALIFIERS, application = Application::class)
class ScreenshotTest {
    @get:Rule
    val rule = createComposeRule()

    private val app: Application get() = ApplicationProvider.getApplicationContext()

    @Before
    fun setUp() {
        SuiteFonts.init(app)
        Dd.get(app).engine.setBaseUrl(engine.url)
        Dd.get(app).prefs.setOnboarded(true)
        engine.connected = true
        scanPreview = null
        val prefs = Dd.get(app).prefs
        listOf("clock", "weather", "spark").forEach { if (it !in prefs.favourites.value) prefs.toggleFavourite(it) }
    }

    /** Lets network callbacks land and coroutine delays run (the compose clock doesn't advance by itself here). */
    private fun settle(ms: Long = 2500) {
        var t = 0L
        while (t < ms) {
            rule.mainClock.advanceTimeBy(50)
            Thread.sleep(8)
            t += 50
        }
    }

    private fun look(le: Boolean = false) = SuiteLook(
        mode = if (le) SuiteMode.LowEnergy else SuiteMode.Wake,
        roles = AccentThemes.of(AccentId.Ember),
        motion = MotionPolicy(cut = le, calm = false),
    )

    @Composable
    private fun Host(le: Boolean = false, content: @Composable (NavHostController) -> Unit) {
        val dd = Dd.get(app)
        val view = LocalView.current
        val haptics = remember { SuiteHaptics(view) }
        SuiteTheme(look(le)) {
            CompositionLocalProvider(LocalHaptics provides haptics, LocalDd provides dd, LocalToast provides remember { ToastState() }) {
                Box(Modifier.fillMaxSize().background(Color.Black)) { content(rememberSwipeDismissableNavController()) }
            }
        }
    }

    @Composable
    private fun Page(page: Int, le: Boolean = false, content: @Composable (NavHostController, androidx.compose.foundation.pager.PagerState) -> Unit) =
        Host(le) { nav ->
            val pager = rememberPagerState(initialPage = page) { 5 }
            content(nav, pager)
            SuiteTimeText()
            PageDots(pager)
        }

    private fun shot(name: String, ms: Long = 3000, before: () -> Unit = {}, content: @Composable () -> Unit) {
        rule.mainClock.autoAdvance = false
        rule.setContent(content)
        settle(ms)
        before()
        settle(600)
        rule.onRoot().captureRoboImage("build/outputs/roborazzi/$name.png")
    }

    @Test fun s29_scan() {
        scanPreview = listOf(PanelCandidate("IDM-3F21A0", "AA:BB:CC:3F:21:A0", -58), PanelCandidate("IDM-77B2C1", "AA:BB:CC:77:B2:C1", -71), PanelCandidate("IDM-0A9E44", "AA:BB:CC:0A:9E:44", -84))
        shot("29_Onboarding-scan-list") { Host { ScanScreen(it) } }
    }

    @Test fun s29b_welcome() = shot("29b_Onboarding-welcome") { Host { WelcomeScreen(it) } }
    @Test fun s30_connect() = shot("30_Onboarding-connecting-HI-test", 5000) { Host { ConnectScreen(it, "AA:BB:CC:3F:21:A0", "IDM-3F21A0") } }
    @Test fun s31_panel() = shot("31_Panel") { Host { PanelScreen(it) } }
    @Test fun s32_nowPlaying() = shot("32_Now-Playing") { Page(0) { nav, p -> NowPlayingPage(nav, p) } }
    @Test fun s33_nextPressed() = shot("33_Now-Playing-Next-pressed", before = {
        rule.onNodeWithContentDescription("Next").performTouchInput { down(center) }
    }) { Page(0) { nav, p -> NowPlayingPage(nav, p) } }
    @Test fun s34_full() = shot("34_Full-view") { Host { FullViewScreen() } }
    @Test fun s35_apps() = shot("35_Apps-categories") { Page(1) { nav, p -> AppsPage(nav, p) } }
    @Test fun s36_detail() = shot("36_App-detail") { Host { AppDetailScreen(it, "clock") } }
    @Test fun s37_games() = shot("37_Games") { Page(2) { nav, p -> GamesPage(nav, p) } }
    @Test fun s38_setup() = shot("38_Game-setup") { Host { GameSetupScreen(it, "bomberman") } }
    @Test fun s39_lobbyQr() = shot("39_Lobby-join-QR") { Host { LobbyScreen(it) } }
    @Test fun s40_lobbyPlayers() = shot("40_Lobby-players", before = {
        rule.onRoot().performTouchInput { swipeUp() }
    }) { Host { LobbyScreen(it) } }
    @Test fun s41_gamepad() = shot("41_Gamepad") { Host { GamepadScreen("snake") } }
    @Test fun s42_playlists() = shot("42_Playlists") { Page(3) { nav, p -> PlaylistsPage(nav, p) } }
    @Test fun s43_display() = shot("43_Display-brightness-gauge") { Host { DisplayScreen(it) } }
    @Test fun s44_engine() = shot("44_Engine") { Host { EngineScreen() } }
    @Test fun s45_studio() {
        File(app.filesDir, "deskdot.toml").writeText("lan_studio = true\n")
        shot("45_Studio-share", before = { rule.onNodeWithContentDescription("Share the studio QR").performClick() }) { Host { StudioScreen() } }
    }
    @Test fun s45b_studioMenu() = shot("45b_Studio") { Host { StudioScreen() } }
    @Test fun s46_settings() = shot("46_Settings") { Host { SettingsScreen(it) } }
    @Test fun s47_more() = shot("47_More") { Page(4) { nav, p -> MorePage(nav, p) } }
    @Test fun s49_nowPlayingLe() = shot("49_Now-Playing-LE") { Page(0, le = true) { nav, p -> NowPlayingPage(nav, p) } }
    @Test fun s50_lobbyLe() = shot("50_Lobby-join-QR-LE") { Host(le = true) { LobbyScreen(it) } }

    /**
     * §4.2.8 R1: content never looks faded at rest. At scroll 0 the first item's top is at y ≥ 92 px, and at the end
     * of the list the last item's bottom is at y ≤ 340 px (both outside the 36–92 / 340–396 fade ramps).
     */
    @Test
    fun r1Bounds() {
        lateinit var st: com.deskdot.app.wear.design.SuiteListState
        rule.setContent {
            Host {
                val s = rememberSuiteListState()
                st = s
                SuiteList(s, remember { FocusRequester() }) {
                    item("h") { m -> HeaderItem(m, "First") }
                    (1..8).forEach { i -> item("r$i") { m -> SettingItem(m, Icons.gear, "Row $i", "value") } }
                    item("last") { m -> SettingItem(m, Icons.gear, "Last", "value") }
                }
            }
        }
        rule.waitForIdle()
        val top = rule.onNodeWithContentDescription("First").getBoundsInRoot().top
        assertTrue("first item top $top < 46 dp (92 px)", top >= 46.dp - 0.5.dp)
        rule.runOnIdle { runBlocking { st.lazy.scrollToItem(9, 10_000) } }
        rule.waitForIdle()
        val bottom: Dp = rule.onNodeWithContentDescription("Last, value").getBoundsInRoot().bottom
        assertTrue("last item bottom $bottom > 170 dp (340 px)", bottom <= 170.dp + 0.5.dp)
    }

    companion object {
        lateinit var engine: FakeEngine

        @JvmStatic @BeforeClass fun start() { engine = FakeEngine() }

        @JvmStatic @AfterClass fun stop() { engine.stop() }
    }
}

private const val WEAR_QUALIFIERS = "w208dp-h208dp-small-notlong-round-watch-xhdpi-keyshidden-nonav"
