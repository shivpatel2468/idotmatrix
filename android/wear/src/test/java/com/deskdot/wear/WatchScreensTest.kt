package com.deskdot.wear

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color as AColor
import androidx.activity.ComponentActivity
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeUp
import androidx.compose.ui.unit.dp
import com.deskdot.wear.theme.WatchThemes
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * Every watch screen at the Gen 6's 416 × 416 px with sample data, for the owner's review before anything
 * installs. Files: build/screens/<name>.png (copied into docs for the PR).
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
    private val summary = Summary(true, "connected", "clock", "Clock", 60, "", "cyber")

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
    private fun Watch(content: @Composable () -> Unit) {
        Box(Modifier.size(208.dp).background(Color.Black)) { content() }
    }

    @Composable
    private fun home(table: String) = Watch {
        Home(summary.copy(theme = table), panel(), apps, WatchThemes.get(table).palette(true), {}, {}, {})
    }

    @Test fun home_cyber() {
        rule.setContent { home("cyber") }
        save("01_home-cyber")
    }

    @Test fun home_scrolled_bubble() {
        rule.setContent { home("cyber") }
        rule.waitForIdle()
        rule.onRoot().performTouchInput { swipeUp(startY = centerY + 60f, endY = centerY - 140f) }
        save("02_home-categories-bubble")
    }

    @Test fun home_royal() {
        rule.setContent { home("royal") }
        save("03_home-royal")
    }

    @Test fun home_classic() {
        rule.setContent { home("classic") }
        save("04_home-classic")
    }

    @Test fun category_games() {
        rule.setContent {
            Watch { PickList("Games", listOf("Blocks", "Pong", "Snake"), WatchThemes.get("cyber").palette(true)) {} }
        }
        rule.waitForIdle()
        rule.onRoot().performTouchInput { swipeUp(startY = centerY + 40f, endY = centerY - 80f) }
        save("05_category-games")
    }

    @Test fun ambient() {
        rule.setContent { Watch { AmbientView(summary, panel(), 0) } }
        save("06_sleep")
    }
}
