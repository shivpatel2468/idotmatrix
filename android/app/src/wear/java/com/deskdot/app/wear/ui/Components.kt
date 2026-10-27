package com.deskdot.app.wear.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import com.deskdot.app.wear.Dd
import com.deskdot.app.wear.design.DrawnItem
import com.deskdot.app.wear.design.GlassFactory
import com.deskdot.app.wear.design.GlassKey
import com.deskdot.app.wear.design.GlassVariant
import com.deskdot.app.wear.design.Icons
import com.deskdot.app.wear.design.LocalHaptics
import com.deskdot.app.wear.design.LocalLook
import com.deskdot.app.wear.design.Neutral
import com.deskdot.app.wear.design.OFont
import com.deskdot.app.wear.design.OIcon
import com.deskdot.app.wear.design.PressFeedback
import com.deskdot.app.wear.design.Semantic
import com.deskdot.app.wear.design.SuiteLook
import com.deskdot.app.wear.design.TAlign
import com.deskdot.app.wear.design.TS
import com.deskdot.app.wear.design.TStyle
import com.deskdot.app.wear.design.ToastState
import com.deskdot.app.wear.design.drawGlass
import com.deskdot.app.wear.design.drawIcon
import com.deskdot.app.wear.design.drawRun
import com.deskdot.app.wear.design.outlinePill
import com.deskdot.app.wear.design.pxAt
import com.deskdot.app.wear.design.pxSize
import com.deskdot.app.wear.design.rememberPressLabel
import com.deskdot.app.wear.design.rowPress
import com.deskdot.app.wear.design.textRun
import kotlinx.coroutines.launch

val LocalDd = staticCompositionLocalOf<Dd> { error("Dd not provided") }
val LocalToast = staticCompositionLocalOf<ToastState> { error("Toast not provided") }

/** §1.13 label modes. */
enum class LabelMode { Permanent, OnPress }

/** Glass circle variants used by DeskDot controls (§1.9). */
enum class Btn { Neutral, On, Error }

private val TwoPx = Stroke(4f)

/**
 * A §1.9 glass circle control (d 88 by default, circular target r 48) with its icon and an optional §1.13
 * label in the reserved slot [labelDy] px below the circle centre. The label is drawn outside the pressed
 * (scaled) layer so it never moves with the press; on-press labels fade/slide in per §1.13.
 * Low Energy: a 4 px outline ring (accent when on / pressed), no glass, no motion.
 */
@Composable
fun GlassButton(
    modifier: Modifier,
    icon: OIcon,
    description: String,
    label: String? = null,
    labelMode: LabelMode = LabelMode.Permanent,
    variant: Btn = Btn.Neutral,
    diameter: Int = 88,
    iconSize: Float = 48f,
    labelDy: Float = 69f,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val touch = maxOf(96, diameter + 8)
    val src = remember { MutableInteractionSource() }
    val pressLabel = rememberPressLabel(src, look.motion)
    val glass = remember(look.roles, variant, diameter) {
        when (variant) {
            Btn.Neutral -> GlassFactory.get(GlassKey(diameter, diameter, diameter / 2f, GlassVariant.Neutral))
            Btn.On -> GlassFactory.accentKey(diameter, diameter, diameter / 2f, look.roles, fill = true).let { GlassFactory.get(it) }
            Btn.Error -> GlassFactory.get(GlassKey(diameter, diameter, diameter / 2f, GlassVariant.Error))
        }
    }
    val press = remember(look, diameter) {
        PressFeedback(diameter.toFloat(), diameter.toFloat(), diameter / 2f, 0.92f, Color(0x1AFFFFFF), look.motion, if (look.le) look.roles.accent else null, haptics)
    }
    val iconColor = when {
        variant == Btn.On && !look.le -> look.roles.onAccent
        variant == Btn.On && look.le -> look.roles.accent
        else -> Neutral.onSurface
    }
    Box(
        modifier
            .pxSize(touch, touch)
            .semantics { contentDescription = description }
            .drawWithCache {
                val run = label?.let { textRun(it, TS.labelCtl) }
                onDrawBehind {
                    if (run == null) return@onDrawBehind
                    val cx = size.width / 2f
                    val base = size.height / 2f + labelDy
                    val strong = look.le || variant != Btn.Neutral
                    val col = when {
                        variant == Btn.Error -> Semantic.error
                        strong -> Neutral.onSurface
                        else -> Neutral.onSurfaceVariant
                    }
                    if (labelMode == LabelMode.Permanent) {
                        drawRun(run, cx, base, col, TAlign.InkCenter, if (enabled) 1f else 0.38f)
                        // Pressed: the permanent label brightens to on-surface (§1.6.4).
                        val a = pressLabel.alpha
                        if (a > 0f && col != Neutral.onSurface && variant != Btn.Error) drawRun(run, cx, base, Neutral.onSurface, TAlign.InkCenter, a)
                    } else {
                        val a = pressLabel.alpha
                        if (a > 0f) drawRun(run, cx, base + pressLabel.lift, Neutral.onSurface, TAlign.InkCenter, a)
                    }
                }
            }
            .clickable(interactionSource = src, indication = press, enabled = enabled, role = Role.Button, onClick = onClick)
            .drawBehind {
                val cx = size.width / 2f
                val cy = size.height / 2f
                val r = diameter / 2f
                val alpha = if (enabled) 1f else 0.38f
                if (look.le) {
                    val ring = if (variant == Btn.Error) Semantic.error else if (variant == Btn.On) look.roles.accent else Neutral.outline
                    drawCircle(ring, r - 2f, Offset(cx, cy), alpha = alpha, style = TwoPx)
                } else {
                    drawGlass(glass, cx - r, cy - r, alpha)
                }
                drawIcon(icon, cx, cy, iconSize, iconColor, alpha)
            },
    )
}

/** One control of an [ActionRowItem]. */
@Stable
data class Act(
    val icon: OIcon,
    val label: String,
    val description: String = label,
    val variant: Btn = Btn.Neutral,
    val mode: LabelMode = LabelMode.Permanent,
    val enabled: Boolean = true,
    val onClick: () -> Unit,
)

/**
 * preview `rowActions`: an item of 352 x 140; 3 circles at x −100/0/+100 (screen 108/208/308) or 2 at ±48
 * (screen 160/256), circle centres 21 px above the item centre, labels at +69 (§5.2b, §5.5.2, §5.6, §5.9).
 */
@Composable
fun ActionRowItem(modifier: Modifier, acts: List<Act>) {
    Box(modifier.pxSize(352, 140)) {
        val xs = when (acts.size) {
            1 -> intArrayOf(0)
            2 -> intArrayOf(-48, 48)
            else -> intArrayOf(-100, 0, 100)
        }
        acts.forEachIndexed { i, a ->
            val cx = 176 + xs[i]
            val cy = 70 - 21
            GlassButton(
                Modifier.pxAt(cx - 48, cy - 48, 96, 96),
                icon = a.icon, description = a.description, label = a.label, labelMode = a.mode,
                variant = a.variant, enabled = a.enabled, onClick = a.onClick,
            )
        }
    }
}

/** preview `rowPill`: a w x h glass pill (accent-text or neutral-text) with centred 28 px text; item h + 16. */
@Composable
fun GlassPillItem(
    modifier: Modifier,
    text: String,
    accent: Boolean = false,
    error: Boolean = false,
    w: Int = 240,
    h: Int = 80,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val glass = remember(look.roles, accent, error, w, h) {
        when {
            error -> GlassFactory.get(GlassKey(w, h, h / 2f, GlassVariant.ErrorText))
            accent -> GlassFactory.get(GlassFactory.accentKey(w, h, h / 2f, look.roles, fill = false, text = true))
            else -> GlassFactory.get(GlassKey(w, h, h / 2f, look.textGlass))
        }
    }
    DrawnItem(
        modifier, w, h + 16, description = text,
        press = PressFeedback(w.toFloat(), h.toFloat(), h / 2f, 0.96f, Color(0x1AFFFFFF), look.motion, if (look.le) look.roles.accent else null, haptics),
        onClick = if (enabled) onClick else null,
    ) {
        val run = textRun(text, TS.labelL(look.bold), w - 48f)
        onDrawBehind {
            val a = if (enabled) 1f else 0.38f
            if (look.le) {
                outlinePill(0f, 8f, w.toFloat(), h.toFloat(), color = if (accent) look.roles.accent else if (error) Semantic.error else Neutral.outline)
            } else {
                drawGlass(glass, 0f, 8f, a)
            }
            drawRun(run, w / 2f, 8f + h / 2f + 10f, Neutral.onSurface, TAlign.InkCenter, a)
        }
    }
}

/** preview `rowData`: h 56, label right-aligned at screen x 196 (muted 26 px), value left at x 220 (mono 24 px). */
@Composable
fun DataRowItem(modifier: Modifier, label: String, value: String, valueColor: Color = Neutral.onSurface, onClick: (() -> Unit)? = null) {
    val look = LocalLook.current
    DrawnItem(modifier, 352, 56, description = "$label, $value", onClick = onClick) {
        val l = textRun(label, TS.body26(look.bold), 150f)
        val v = textRun(value, TS.mono(24f), 156f)
        onDrawBehind {
            drawRun(l, 164f, 37f, if (look.le) Neutral.onSurfaceVariant else Neutral.onSurfaceMuted, TAlign.InkEnd)
            drawRun(v, 188f, 37f, valueColor)
        }
    }
}

/**
 * preview `hero`: a ring of d 128 (stroke 6) in the status colour with a 64 px icon, and the title (title-m)
 * 100 px below the ring centre; optional sub-line (body 26, wrapped to 300 px, ≤ 2 lines). [pulse]: the ring
 * breathes 0.4 ↔ 1.0 once per second (Wake only; static in LE / Calm).
 */
@Composable
fun HeroItem(modifier: Modifier, icon: OIcon, color: Color, title: String, sub: String? = null, pulse: Boolean = false, h: Int = 200) {
    val look = LocalLook.current
    val alpha = remember { Animatable(1f) }
    val doPulse = pulse && !look.le && !look.motion.cut && !look.calm
    LaunchedEffect(doPulse) {
        if (doPulse) {
            alpha.animateTo(0.4f, infiniteRepeatable(tween(500, easing = LinearEasing), RepeatMode.Reverse))
        } else {
            alpha.snapTo(1f)
        }
    }
    val lines = sub?.let { wrap(it, TS.body26(look.bold), 300f, 2) }.orEmpty()
    val total = h + lines.size * 34
    DrawnItem(modifier, 352, total, description = listOfNotNull(title, sub).joinToString(". ")) {
        val t = textRun(title, TS.titleM(look.bold), 330f)
        val runs = lines.map { textRun(it, TS.body26(look.bold)) }
        onDrawBehind {
            val cy = h / 2f - 36f
            drawCircle(color, 61f, Offset(176f, cy), alpha = alpha.value, style = Stroke(6f))
            drawIcon(icon, 176f, cy, 64f, color)
            drawRun(t, 176f, cy + 100f + 11f, Neutral.onSurface, TAlign.InkCenter)
            runs.forEachIndexed { i, r -> drawRun(r, 176f, cy + 146f + i * 34f, look.variantText, TAlign.InkCenter) }
        }
    }
}

/** Greedy word wrap with ellipsis on the last line (measured once, in composition). */
fun wrap(text: String, style: TStyle, maxW: Float, maxLines: Int): List<String> {
    val p = com.deskdot.app.wear.design.Ink.paint(style)
    val words = text.trim().split(Regex("\\s+"))
    val out = ArrayList<String>()
    var line = ""
    for (w in words) {
        val cand = if (line.isEmpty()) w else "$line $w"
        if (p.measureText(cand) <= maxW || line.isEmpty()) {
            line = cand
        } else {
            out.add(line)
            line = w
            if (out.size == maxLines) break
        }
    }
    if (out.size < maxLines && line.isNotEmpty()) out.add(line)
    else if (out.size == maxLines && line.isNotEmpty() && words.isNotEmpty()) {
        val last = out.removeAt(out.size - 1)
        out.add(android.text.TextUtils.ellipsize("$last …", p, maxW, android.text.TextUtils.TruncateAt.END).toString())
    }
    return out
}

/** A centred block of wrapped body text (descriptions, explanations), body 26 on-surface-variant. */
@Composable
fun TextBlockItem(modifier: Modifier, text: String, maxLines: Int = 4, color: Color? = null, w: Float = 330f) {
    val look = LocalLook.current
    val lines = remember(text, look.bold) { wrap(text, TS.body26(look.bold), w, maxLines) }
    DrawnItem(modifier, 352, 34 * lines.size + 14, description = text) {
        val runs = lines.map { textRun(it, TS.body26(look.bold)) }
        onDrawBehind { runs.forEachIndexed { i, r -> drawRun(r, 176f, 34f + i * 34f - 6f, color ?: look.variantText, TAlign.InkCenter) } }
    }
}

/**
 * preview `rowLetter` / `rowApp`: 104 (120 with a sub-line in LE) high; a 80 px circle in [dot] with the first
 * letter in black (≥ 7:1 on every category colour), the name in title-m at x −64 and an optional sub-line.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun LetterRowItem(
    modifier: Modifier,
    name: String,
    dot: Color,
    sub: String? = null,
    dim: Boolean = false,
    trailingCheck: Boolean? = null,
    onClick: (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val h = if (look.le || sub != null) 120 else 104
    DrawnItem(
        modifier, 352, h, description = listOfNotNull(name, sub).joinToString(", "),
        press = rowPress(look, 352f, h.toFloat(), haptics), onClick = onClick, onLongClick = onLongClick,
    ) {
        val n = textRun(name, TS.titleM(look.bold), if (trailingCheck != null) 196f else 236f)
        val s = sub?.let { textRun(it, TS.body26(look.bold), 236f) }
        val letter = textRun(name.firstOrNull { it.isLetterOrDigit() }?.uppercaseChar()?.toString() ?: "•", com.deskdot.app.wear.design.TStyle(OFont.G700, 35f))
        onDrawBehind {
            val cy = size.height / 2f
            val a = if (dim) 0.5f else 1f
            val circle = if (look.le) grey(dot) else dot
            drawCircle(circle, 40f, Offset(52f, cy), alpha = a * (if (look.le) 0.8f else 1f))
            drawRun(letter, 52f, cy + 12.6f, Color.Black, TAlign.InkCenter, a)
            if (s != null) {
                drawRun(n, 112f, cy - 6f, Neutral.onSurface, alpha = a)
                drawRun(s, 112f, cy + 28f, look.variantText, alpha = a)
            } else {
                drawRun(n, 112f, cy + 11f, Neutral.onSurface, alpha = a)
            }
            if (trailingCheck != null) checkCircle(316f, cy, trailingCheck, look)
        }
    }
}

/** §5.6 multi-select check circle (24 px; filled accent with a check when selected). */
fun DrawScope.checkCircle(cx: Float, cy: Float, on: Boolean, look: SuiteLook) {
    if (on) {
        drawCircle(look.roles.accent, 24f, Offset(cx, cy))
        drawIcon(Icons.check, cx, cy, 32f, look.roles.onAccent)
    } else {
        drawCircle(Neutral.outline, 22f, Offset(cx, cy), style = TwoPx)
    }
}

fun grey(c: Color): Color {
    val l = 0.3f * c.red + 0.59f * c.green + 0.11f * c.blue
    return Color(l, l, l, c.alpha)
}

/** preview `gamesList` row: 120 high; a surface-2 circle d 80 with a 40 px icon in accent-light, name + sub. */
@Composable
fun IconRowItem(modifier: Modifier, icon: OIcon, name: String, sub: String?, iconColor: Color? = null, dim: Boolean = false, onClick: () -> Unit) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    DrawnItem(modifier, 352, 120, description = listOfNotNull(name, sub).joinToString(", "), press = rowPress(look, 352f, 120f, haptics), onClick = onClick) {
        val n = textRun(name, TS.titleM(look.bold), 236f)
        val s = sub?.let { textRun(it, TS.body26(look.bold), 236f) }
        onDrawBehind {
            val cy = size.height / 2f
            val a = if (dim) 0.5f else 1f
            if (look.le) drawCircle(Neutral.outline, 38f, Offset(52f, cy), style = TwoPx) else drawCircle(Neutral.surface2, 40f, Offset(52f, cy), alpha = a)
            drawIcon(icon, 52f, cy, 40f, iconColor ?: look.roles.accentLight, a)
            if (s != null) {
                drawRun(n, 112f, cy - 6f, Neutral.onSurface, alpha = a)
                drawRun(s, 112f, cy + 30f, look.variantText, alpha = a)
            } else {
                drawRun(n, 112f, cy + 11f, Neutral.onSurface, alpha = a)
            }
        }
    }
}

/** preview `rowSearch`: a 240 x 80 neutral-text glass pill with the search icon and "Search"; item 96. */
@Composable
fun SearchPillItem(modifier: Modifier, text: String = "Search", onClick: () -> Unit) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val glass = remember(look.textGlass) { GlassFactory.get(GlassKey(240, 80, 40f, look.textGlass)) }
    DrawnItem(
        modifier, 240, 96, description = text,
        press = PressFeedback(240f, 80f, 40f, 0.96f, Color(0x1AFFFFFF), look.motion, if (look.le) look.roles.accent else null, haptics),
        onClick = onClick,
    ) {
        val t = textRun(text, TS.labelL(look.bold), 150f)
        onDrawBehind {
            if (look.le) outlinePill(0f, 8f, 240f, 80f) else drawGlass(glass, 0f, 8f)
            val gw = 40f + 12f + t.inkWidth
            val x0 = 120f - gw / 2f
            drawIcon(Icons.search, x0 + 20f, 48f, 40f, look.variantText)
            drawRun(t, x0 + 52f - t.inkLeft, 58f, look.variantText)
        }
    }
}

/**
 * §4.2.2 favourites row: up to 3 circles d 88 at x −108/0/+108, 18 px above the item centre; the reserved label
 * line (baseline 129 from the top) shows the pressed app's name (on-press, §1.13).
 */
@Composable
fun FavouritesRowItem(modifier: Modifier, apps: List<Pair<String, Color>>, onOpen: (Int) -> Unit) {
    Box(modifier.pxSize(352, 140)) {
        apps.take(3).forEachIndexed { i, (name, color) ->
            val cx = 176 + intArrayOf(-108, 0, 108)[i]
            FavCircle(Modifier.pxAt(cx - 52, 52 - 52, 104, 104), name, color) { onOpen(i) }
        }
    }
}

@Composable
private fun FavCircle(modifier: Modifier, name: String, color: Color, onClick: () -> Unit) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val src = remember { MutableInteractionSource() }
    val label = rememberPressLabel(src, look.motion)
    val press = remember(look) { PressFeedback(88f, 88f, 44f, 0.92f, Color(0x1AFFFFFF), look.motion, if (look.le) look.roles.accent else null, haptics) }
    Box(
        modifier
            .semantics { contentDescription = name }
            .drawWithCache {
                val run = textRun(name, TS.labelCtl, 280f)
                onDrawBehind { drawRun(run, 52f, 129f, Neutral.onSurface, TAlign.InkCenter, label.alpha) }
            }
            .clickable(interactionSource = src, indication = press, role = Role.Button, onClick = onClick)
            .drawWithCache {
                val letter = textRun(name.firstOrNull()?.uppercaseChar()?.toString() ?: "•", com.deskdot.app.wear.design.TStyle(OFont.G700, 38.7f))
                val rim = GlassFactory.get(GlassKey(88, 88, 44f, GlassVariant.Neutral))
                onDrawBehind {
                    val c = if (look.le) grey(color) else color
                    drawCircle(c, 44f, Offset(52f, 52f), alpha = if (look.le) 0.8f else 1f)
                    if (!look.le) drawGlass(rim, 8f, 8f, 0.5f)
                    drawRun(letter, 52f, 52f + 13.9f, if (look.le) Color.Black else Color.White, TAlign.InkCenter)
                }
            },
    )
}

/** §5.2a / §5.3 indeterminate edge arc: r 200, stroke 6, 60° long, one turn per 1.2 s (Wake only). */
@Composable
fun ScanArc(visible: Boolean) {
    val look = LocalLook.current
    if (!visible || look.le) return
    val angle = remember { Animatable(0f) }
    LaunchedEffect(Unit) {
        angle.animateTo(360f, infiniteRepeatable(tween(if (look.calm) 2400 else 1200, easing = LinearEasing)))
    }
    Spacer(
        Modifier.fillMaxSize().drawBehind {
            drawArc(
                look.roles.accent, angle.value - 90f, 60f, false,
                topLeft = Offset(8f, 8f), size = Size(400f, 400f),
                style = Stroke(6f, cap = StrokeCap.Round),
            )
        },
    )
}

/** Two pills side by side (Yes/No, Retry/Choose another): each w x 72 at ±74 px from centre (preview `connecting`). */
@Composable
fun PillPair(
    modifier: Modifier,
    left: String,
    right: String,
    leftAccent: Boolean = true,
    onLeft: () -> Unit,
    onRight: () -> Unit,
    w: Int = 140,
) {
    Box(modifier.pxSize(352, 88)) {
        GlassPillItem(Modifier.pxAt(176 - 4 - w, 0, w, 88), left, accent = leftAccent, w = w, h = 72, onClick = onLeft)
        GlassPillItem(Modifier.pxAt(176 + 4, 0, w, 88), right, accent = false, w = w, h = 72, onClick = onRight)
    }
}

/** Remembers a "tap again to confirm" state that reverts after 2.5 s (§4.7 Hide, §5.2b Forget, §5.9 Stop). */
@Stable
class Confirm {
    var armed by mutableStateOf(false)
        private set
    private var job: kotlinx.coroutines.Job? = null

    fun tap(scope: kotlinx.coroutines.CoroutineScope, onConfirmed: () -> Unit) {
        if (armed) {
            job?.cancel()
            armed = false
            onConfirmed()
        } else {
            armed = true
            job?.cancel()
            job = scope.launch {
                kotlinx.coroutines.delay(2500)
                armed = false
            }
        }
    }
}

@Composable
fun rememberConfirm(): Confirm = remember { Confirm() }

/** A header row with a value line in a status colour (used by small status screens). */
@Composable
fun StatusLineItem(modifier: Modifier, text: String, color: Color) {
    val look = LocalLook.current
    DrawnItem(modifier, 352, 48, description = text) {
        val r = textRun(text, TS.body26(look.bold), 330f)
        onDrawBehind { drawRun(r, 176f, 32f, color, TAlign.InkCenter) }
    }
}

/** Generic tap handler with haptics for whole-item taps where a press indication is not wanted. */
fun Modifier.tap(onClick: () -> Unit): Modifier = this.clickable(interactionSource = null, indication = null, onClick = onClick)

/** Mutable float holder read only in draw (crown overlays). */
@Stable
class DrawFloat(v: Float = 0f) {
    var value by mutableFloatStateOf(v)
}

@Composable
fun rememberScopeLaunch(): kotlinx.coroutines.CoroutineScope = rememberCoroutineScope()

