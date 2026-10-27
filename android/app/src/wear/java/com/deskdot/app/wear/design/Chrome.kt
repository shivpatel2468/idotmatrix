package com.deskdot.app.wear.design

import android.graphics.Path
import android.graphics.RectF
import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.PagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import java.util.Calendar
import kotlin.math.abs

private const val TT_R = 186f

/**
 * §1.7 / §1.12 curved TimeText: label-m on a baseline circle of r 186 centred on 12 o'clock,
 * on-surface-variant (LE: on-surface wght 700). NOTHING is drawn behind it (rev 1.2): no shadow,
 * halo, scrim, plate or band — the content below fades itself out with the edge mask instead.
 * Thermal Calm appends "· [thermostat] Calm" in warn (§4.6, I-22).
 * The clock ticks once per minute and only while the activity is resumed.
 */
@Composable
fun SuiteTimeText(modifier: Modifier = Modifier) {
    val look = LocalLook.current
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    var now by remember { mutableStateOf(formatClock(context)) }
    LaunchedEffect(lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                now = formatClock(context)
                val t = System.currentTimeMillis()
                delay(60_000L - t % 60_000L + 50L)
            }
        }
    }
    val calm = look.calm
    val le = look.le
    Spacer(
        modifier
            .fillMaxSize()
            .drawWithCache {
                val style = TS.labelM(le)
                val paint = Ink.paint(style)
                val path = Path().apply { addArc(RectF(208f - TT_R, 208f - TT_R, 208f + TT_R, 208f + TT_R), -150f, 120f) }
                val arcLen = TT_R * (Math.PI * 2.0 / 3.0).toFloat()
                val wTime = paint.measureText(now)
                val dot = " · "
                val wDot = paint.measureText(dot)
                val wCalm = paint.measureText("Calm")
                val iconW = 20f
                val total = if (calm) wTime + wDot + iconW + 3f + wCalm else wTime
                val start = (arcLen - total) / 2f
                val timeColor = (if (le || look.sun) Neutral.onSurface else Neutral.onSurfaceVariant).toArgb()
                val warn = Semantic.warn.toArgb()
                val iconAt = start + wTime + wDot + iconW / 2f
                val iconDeg = -150f + (iconAt / TT_R) * (180f / Math.PI.toFloat()) + 90f
                onDrawBehind {
                    val c = drawContext.canvas.nativeCanvas
                    paint.color = timeColor
                    c.drawTextOnPath(now, path, start, 0f, paint)
                    if (calm) {
                        paint.color = warn
                        c.drawTextOnPath(dot, path, start + wTime, 0f, paint)
                        c.drawTextOnPath("Calm", path, start + wTime + wDot + iconW + 3f, 0f, paint)
                        rotate(iconDeg, Offset(208f, 208f)) {
                            drawIcon(Icons.thermostat, 208f, 208f - TT_R - 8.5f, iconW, Semantic.warn)
                        }
                    }
                }
            },
    )
}

private fun formatClock(context: android.content.Context): String {
    val cal = Calendar.getInstance()
    val m = cal.get(Calendar.MINUTE)
    val h = if (android.text.format.DateFormat.is24HourFormat(context)) {
        cal.get(Calendar.HOUR_OF_DAY)
    } else {
        (cal.get(Calendar.HOUR) + 11) % 12 + 1
    }
    return if (m < 10) "$h:0$m" else "$h:$m"
}

/**
 * §4.3 page indicator: n dots (DeskDot: 5, §5.1) of 12 px, pitch 24 px, centred at y 402 (preview). Selected accent,
 * others #FFF @ 30% (LE: on-surface / outline). Colour follows the swipe in the draw phase only.
 */
@Composable
fun PageDots(pager: PagerState, modifier: Modifier = Modifier, count: Int = pager.pageCount) {
    val look = LocalLook.current
    val sel = if (look.le) Neutral.onSurface else look.roles.accent
    val off = if (look.le) Neutral.outline else Neutral.white30
    Spacer(
        modifier
            .fillMaxSize()
            .drawBehind {
                val pos = pager.currentPage + pager.currentPageOffsetFraction
                val x0 = 208f - (count - 1) * 12f
                for (i in 0 until count) {
                    val t = (1f - abs(pos - i)).coerceIn(0f, 1f)
                    drawCircle(lerp(off, sel, t), 6f, Offset(x0 + 24f * i, 402f))
                }
            },
    )
}

/** §4.8 toast: capsule 320 x 80 px centred at (208, 332), 1500 ms. */
@Stable
class ToastState {
    var message by mutableStateOf<String?>(null)
        private set
    var serial by mutableStateOf(0)
        private set

    fun show(text: String) {
        message = text
        serial++
    }

    internal fun clear(forSerial: Int) {
        if (serial == forSerial) message = null
    }
}

@Composable
fun SuiteToast(state: ToastState) {
    val look = LocalLook.current
    val msg = state.message ?: return
    val serial = state.serial
    val anim = remember(serial) { Animatable(0f) }
    LaunchedEffect(serial) {
        anim.animateTo(1f, look.motion.tween(200, Ease.emphasizedDecel))
        delay(1500)
        anim.animateTo(0f, look.motion.tween(150, Ease.standardAccel))
        state.clear(serial)
    }
    val glass = remember(look.textGlass) { GlassFactory.get(GlassKey(320, 80, 40f, look.textGlass)) }
    Spacer(
        Modifier
            .fillMaxSize()
            .drawWithCache {
                val run = textRun(msg, TS.labelL(look.bold), 320f - 48f)
                onDrawBehind {
                    val a = anim.value
                    val dy = (1f - a) * 16f
                    if (look.le) {
                        drawRoundRect(Color.Black, Offset(48f, 292f + dy), androidx.compose.ui.geometry.Size(320f, 80f), androidx.compose.ui.geometry.CornerRadius(40f), alpha = a)
                        drawRoundRect(
                            Neutral.outline, Offset(50f, 294f + dy), androidx.compose.ui.geometry.Size(316f, 76f),
                            androidx.compose.ui.geometry.CornerRadius(38f), alpha = a,
                            style = androidx.compose.ui.graphics.drawscope.Stroke(4f),
                        )
                    } else {
                        drawGlass(glass, 48f, 292f + dy, a)
                    }
                    drawRun(run, 208f, 332f + dy + 10f, Neutral.onSurface, TAlign.InkCenter, a)
                }
            },
    )
}
