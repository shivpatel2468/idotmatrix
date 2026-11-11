package com.deskdot.wear

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color as AColor
import androidx.activity.ComponentActivity
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performRotaryScrollInput
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeUp
import androidx.compose.ui.unit.dp
import com.deskdot.wear.design.Icons
import com.deskdot.wear.design.LocalLook
import com.deskdot.wear.design.Look
import org.json.JSONObject
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * Every watch screen at the Gen 6's 416 × 416 px with sample data, for the owner's review before anything
 * installs: Cyber grid, Classic green, Royal blue (dark) and Cyber grid light. Files: build/screens/<name>.png
 * (copied into android/wear/screenshots for the PR).
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(qualifiers = "w208dp-h208dp-round-xhdpi", sdk = [30])
class WatchScreensTest {
    @get:Rule
    val rule = createAndroidComposeRule<ComponentActivity>()

    private val apps = listOf(
        AppItem("snake", "Snake", "games"), AppItem("tetris", "Blocks", "games"), AppItem("pong", "Pong", "games"),
        AppItem("roulette", "Roulette", "casino"), AppItem("blackjack", "Blackjack", "casino"),
        AppItem("cat", "Cat", "pets"), AppItem("clock", "Clock", "time"), AppItem("countdown", "Countdown", "time"),
        AppItem("weather", "Weather", "data"), AppItem("stocks", "Stocks", "data"), AppItem("nowplaying", "Now playing", "media"),
        AppItem("canvas", "Canvas", "creative"), AppItem("fire", "Fire", "ambient"), AppItem("pomodoro", "Focus timer", "productivity"),
    )

    /** What today's phone app (3.9.0) sends: the engine's current object as raw text, in both fields. */
    private val raw = """{"key":"clock","app":"clock","item":null,"kind":"stream","status":null}"""

    // The summary goes through the same parser as the phone's reply, so these screens prove the name fix too.
    private fun parsed(table: String) = parseSummary(
        JSONObject().put("connected", true).put("status", "connected").put("current", raw).put("name", raw)
            .put("brightness", 60).put("preset", "").put("theme", table),
    )

    /** A 32 × 32 "panel" picture: a pixel clock face, so the preview reads like the real thing. */
    private fun panel() = Bitmap.createBitmap(32, 32, Bitmap.Config.ARGB_8888).apply {
        for (y in 0 until 32) for (x in 0 until 32) {
            val dx = x - 15.5; val dy = y - 15.5
            val r = Math.sqrt(dx * dx + dy * dy)
            setPixel(x, y, when {
                r in 13.0..14.5 -> AColor.rgb(0, 210, 190)
                x == 16 && y in 8..16 -> AColor.WHITE
                y == 16 && x in 16..22 -> AColor.rgb(255, 72, 24)
                else -> AColor.BLACK
            })
        }
    }.asImageBitmap()

    private fun save(name: String) {
        rule.waitForIdle()
        rule.mainClock.advanceTimeBy(2000)
        rule.waitForIdle()
        val v = rule.activity.window.decorView
        val bmp = Bitmap.createBitmap(416, 416, Bitmap.Config.ARGB_8888)
        rule.runOnUiThread { v.draw(Canvas(bmp)) }
        val out = File("build/screens/$name.png").apply { parentFile!!.mkdirs() }
        out.outputStream().use { bmp.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    @Composable
    private fun Watch(table: String, dark: Boolean = true, content: @Composable () -> Unit) {
        val look = Look(table, dark)
        CompositionLocalProvider(LocalLook provides look) {
            Box(Modifier.size(208.dp).background(look.bg)) { content() }
        }
    }

    private fun home(table: String, dark: Boolean) {
        rule.setContent { Watch(table, dark) { Home(parsed(table), panel(), apps, {}, {}, {}, {}) } }
    }

    @Test fun t01_home_cyber() { home("cyber", true); save("01_home-cyber") }
    @Test fun t02_home_classic() { home("classic", true); save("02_home-classic") }
    @Test fun t03_home_royal() { home("royal", true); save("03_home-royal") }
    @Test fun t04_home_cyber_light() { home("cyber", false); save("04_home-cyber-light") }

    private fun kinds(table: String, dark: Boolean) {
        home(table, dark)
        rule.waitForIdle()
        rule.onRoot().performTouchInput { swipeUp(startY = centerY + 80f, endY = centerY - 200f) }
    }

    @Test fun t05_kinds_cyber() { kinds("cyber", true); save("05_kinds-cyber") }
    @Test fun t06_kinds_classic() { kinds("classic", true); save("06_kinds-classic") }
    @Test fun t07_kinds_royal() { kinds("royal", true); save("07_kinds-royal") }
    @Test fun t08_kinds_cyber_light() { kinds("cyber", false); save("08_kinds-cyber-light") }

    private fun games(table: String, dark: Boolean) {
        rule.setContent { Watch(table, dark) { PickList("Games", Icons.games, listOf("Blocks", "Pong", "Snake"), on = 2) {} } }
        rule.waitForIdle()
        rule.onRoot().performTouchInput { swipeUp(startY = centerY + 40f, endY = centerY - 80f) }
    }

    @Test fun t09_games_cyber() { games("cyber", true); save("09_games-cyber") }
    @Test fun t10_games_classic() { games("classic", true); save("10_games-classic") }
    @Test fun t11_games_royal() { games("royal", true); save("11_games-royal") }
    @Test fun t12_games_cyber_light() { games("cyber", false); save("12_games-cyber-light") }

    /** The crown alone (no touch) scrolls Home: the list takes the crown's focus by itself. */
    @OptIn(ExperimentalTestApi::class)
    @Test fun t13_crown_scrolls_home() {
        home("cyber", true)
        rule.mainClock.advanceTimeBy(100)
        rule.waitForIdle()
        rule.onRoot().performRotaryScrollInput { rotateToScrollVertically(260f) }
        save("13_crown-scrolled-cyber")
    }

    @Test fun t14_sleep() {
        val s = parsed("cyber")
        rule.setContent { Watch("cyber") { AmbientView(s.copy(name = shownName(s, apps)), panel(), 0) } }
        save("14_sleep")
    }
}
