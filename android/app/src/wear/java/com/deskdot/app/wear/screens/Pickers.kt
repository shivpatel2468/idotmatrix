package com.deskdot.app.wear.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.navigation.NavHostController
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
import com.deskdot.app.wear.design.pxAt
import com.deskdot.app.wear.design.pxSize
import com.deskdot.app.wear.design.rememberSuiteListState
import com.deskdot.app.wear.design.textRun
import com.deskdot.app.wear.nav.Pick
import com.deskdot.app.wear.ui.FocusWhenActive
import com.deskdot.app.wear.ui.GlassButton
import com.deskdot.app.wear.ui.Screen
import com.deskdot.app.wear.ui.crownSteps
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** A radio list (§4.9 pickers): one row per option, a check on the selected one; tap applies and returns. */
@Composable
fun ChoiceScreen(nav: NavHostController) {
    val req = remember { Pick.choice } ?: return run { nav.popBackStack(); Unit }
    val haptics = LocalHaptics.current
    var sel by remember { mutableStateOf(req.selected) }
    val state = rememberSuiteListState(initialIndex = 0)
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    Screen {
        SuiteList(state, focus) {
            item("h") { HeaderItem(it, req.title) }
            items(req.options, key = { it.first }) { (value, label), m ->
                SettingItem(m, null, label, null, if (value == sel) Trailing.Check else Trailing.None, onClick = {
                    sel = value
                    haptics.confirm()
                    req.onPick(value)
                    nav.popBackStack()
                })
            }
        }
    }
}

/**
 * A crown stepper laid out like the §5.8 gauge: arc r 164 (stroke 16, 270°), the value (80 px, baseline 214),
 * the title in the reserved label line (baseline 246) and −/+ at (160, 300) / (256, 300). Every change calls
 * the request's onChange once the crown rests for 300 ms (one engine call per gesture, not per detent).
 */
@Composable
fun NumberScreen() {
    val req = remember { Pick.number } ?: return
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val scope = rememberCoroutineScope()
    var v by remember { mutableDoubleStateOf(req.value) }
    var job by remember { mutableStateOf<Job?>(null) }
    var lastDir by remember { mutableStateOf(0) }
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)

    fun step(d: Int) {
        val n = req.step(v, d)
        if (n == v) {
            haptics.reject()
            return
        }
        haptics.tick()
        v = n
        lastDir = d
        job?.cancel()
        job = scope.launch {
            delay(300)
            req.onChange(v)
        }
    }

    Screen {
        Box(Modifier.fillMaxSize().crownSteps(focus) { step(it) }) {
            Spacer(
                Modifier.fillMaxSize().drawWithCache {
                    val text = req.format(v)
                    val big = textRun(text, TStyle(OFont.G600.bumped(look.bold), if (text.length > 4) 64f else 80f, tnum = true), 260f)
                    val title = textRun(req.title, TS.labelM(look.bold), 220f)
                    onDrawBehind {
                        val st = Stroke(16f, cap = StrokeCap.Round)
                        drawArc(if (look.le) Neutral.outline else Neutral.surface2, 135f, 270f, false, Offset(44f, 44f), Size(328f, 328f), style = st)
                        val frac = ((v - req.min) / (req.max - req.min)).toFloat().coerceIn(0f, 1f)
                        if (frac > 0f) drawArc(look.roles.accent, 135f, 270f * frac, false, Offset(44f, 44f), Size(328f, 328f), style = st)
                        drawRun(big, 208f, 214f, Neutral.onSurface, TAlign.InkCenter)
                        drawRun(title, 208f, 246f, look.variantText, TAlign.InkCenter)
                    }
                },
            )
            GlassButton(Modifier.pxAt(160 - 48, 300 - 48, 96, 96), Icons.remove, "Less", iconSize = 40f) { step(-1) }
            GlassButton(Modifier.pxAt(256 - 48, 300 - 48, 96, 96), Icons.add, "More", iconSize = 40f) { step(1) }
        }
    }
}

/** §5.4 colour setting: the meta palette as rows of 3 circles of 64 px at pitch 76, selected ringed in on-surface. */
@Composable
fun ColorScreen(nav: NavHostController) {
    val req = remember { Pick.color } ?: return run { nav.popBackStack(); Unit }
    val haptics = LocalHaptics.current
    val state = rememberSuiteListState()
    val focus = remember { FocusRequester() }
    FocusWhenActive(focus)
    val rows = remember(req) { req.palette.chunked(3) }
    Screen {
        SuiteList(state, focus) {
            item("h") { HeaderItem(it, req.title) }
            rows.forEachIndexed { r, row ->
                item("r$r") {
                    SwatchRow(it, row, req.selected) { hex ->
                        haptics.confirm()
                        req.onPick(hex)
                        nav.popBackStack()
                    }
                }
            }
        }
    }
}

@Composable
private fun SwatchRow(modifier: Modifier, row: List<Pair<String, String>>, selected: String?, onPick: (String) -> Unit) {
    Box(modifier.pxSize(352, 80)) {
        row.forEachIndexed { i, (name, hex) ->
            val c = runCatching { Color(android.graphics.Color.parseColor(hex)) }.getOrDefault(Color.Gray)
            val on = hex.equals(selected, true)
            DrawnItem(Modifier.pxAt(176 + (i - 1) * 76 - 38, 0, 76, 80), 76, 80, description = name, onClick = { onPick(hex) }) {
                onDrawBehind {
                    drawCircle(c, 32f, Offset(38f, 40f))
                    if (on) drawCircle(Neutral.onSurface, 36f, Offset(38f, 40f), style = Stroke(4f))
                }
            }
        }
    }
}
