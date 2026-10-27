package com.deskdot.app.wear.design

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.CacheDrawScope
import androidx.compose.ui.draw.DrawResult
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.layout.layout
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Constraints

/** Exact pixel size, independent of density (the spec is written in px). */
fun Modifier.pxSize(w: Int, h: Int): Modifier = layout { m, _ ->
    val p = m.measure(Constraints.fixed(w, h))
    layout(w, h) { p.place(0, 0) }
}

/** Absolute pixel position for fixed layouts (Controls, menus). */
fun Modifier.pxAt(x: Int, y: Int, w: Int, h: Int): Modifier = layout { m, c ->
    val p = m.measure(Constraints.fixed(w, h))
    layout(c.maxWidth, c.maxHeight) { p.place(x, y) }
}

@Composable
fun rememberGlass(key: GlassKey): GlassImage = remember(key) { GlassFactory.get(key) }

/** LE outline pill/circle (§4.1: glass becomes a 2 dp outline). */
fun DrawScope.outlinePill(x: Float, y: Float, w: Float, h: Float, color: Color = Neutral.outline, sw: Float = 4f, radius: Float = (h - sw) / 2f) {
    drawRoundRect(color, Offset(x + sw / 2f, y + sw / 2f), Size(w - sw, h - sw), CornerRadius(radius), style = Stroke(sw))
}

fun rowPress(look: SuiteLook, w: Float, h: Float, haptics: SuiteHaptics, radius: Float = h / 2f, scale: Float = 0.97f, fill: Color = Color(0x14FFFFFF)) =
    PressFeedback(w, h, radius, scale, fill, look.motion, if (look.le) look.roles.accent else null, haptics)

/** A list item of exact pixel size, drawn entirely by [draw] (centre-relative coords via translate). */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun DrawnItem(
    modifier: Modifier,
    w: Int,
    h: Int,
    description: String? = null,
    press: PressFeedback? = null,
    onClick: (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
    draw: CacheDrawScope.() -> DrawResult,
) {
    val src = remember { MutableInteractionSource() }
    var m = modifier.pxSize(w, h)
    if (description != null) m = m.semantics { contentDescription = description }
    if (onClick != null || onLongClick != null) {
        m = m.combinedClickable(
            interactionSource = src,
            indication = press,
            role = Role.Button,
            onClick = onClick ?: {},
            onLongClick = onLongClick,
        )
    }
    Box(m.drawWithCache(draw))
}

// ------------------------------------------------------------------------------------------------
// Row builders that mirror preview.html (rowHeader / rowCaption / rowSetting / rowFooter / rowPill)
// ------------------------------------------------------------------------------------------------

/** preview rowHeader: h 64, 40 px title ink-centred, baseline +14 from centre. */
@Composable
fun HeaderItem(modifier: Modifier, text: String, sub: String? = null) {
    val look = LocalLook.current
    val h = if (sub != null) 104 else 64
    DrawnItem(modifier, 352, h, description = text) {
        val t = textRun(text, TS.titleL(look.bold), 340f)
        val s = sub?.let { textRun(it, TS.body26(look.bold), 340f) }
        onDrawBehind {
            val cy = size.height / 2f
            if (s == null) {
                drawRun(t, 176f, cy + 14f, Neutral.onSurface, TAlign.InkCenter)
            } else {
                drawRun(t, 176f, cy - 8f, Neutral.onSurface, TAlign.InkCenter)
                drawRun(s, 176f, cy + 32f, look.variantText, TAlign.InkCenter)
            }
        }
    }
}

/** preview rowCaption: h 48, label-m 24 px, muted (LE on-surface-variant wght 700), baseline +8. */
@Composable
fun CaptionItem(modifier: Modifier, text: String, onLongClick: (() -> Unit)? = null) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    DrawnItem(
        modifier, 352, 48, description = text,
        onClick = if (onLongClick != null) ({}) else null,
        onLongClick = onLongClick?.let { { haptics.longPress(); it() } },
    ) {
        val t = textRun(text, TS.labelM(look.le))
        onDrawBehind { drawRun(t, 176f, 24f + 8f, if (look.le) Neutral.onSurfaceVariant else Neutral.onSurfaceMuted, TAlign.InkCenter) }
    }
}

enum class Trailing { None, Swatch, SwitchOn, SwitchOff, Chevron, Check }

/**
 * §4.9 settings row = preview rowSetting: 352 x 104 (LE 120) surface-1 pill (LE: 2 px outline),
 * 48 px icon at x -128, title 28 px at x -92 baseline -6 (or +10 without a value), value 26 px
 * on-surface-variant baseline +26, text clipped at x +72; trailing zone +84..+156.
 */
@Composable
fun SettingItem(
    modifier: Modifier,
    icon: OIcon?,
    title: String,
    value: String? = null,
    trailing: Trailing = Trailing.None,
    swatch: Color? = null,
    titleColor: Color = Neutral.onSurface,
    onClick: (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val h = if (look.le) 120 else 104
    DrawnItem(
        modifier, 352, h, description = listOfNotNull(title, value).joinToString(", "),
        press = rowPress(look, 352f, h.toFloat(), haptics, scale = 0.97f),
        onClick = onClick, onLongClick = onLongClick,
    ) {
        val textMax = if (trailing == Trailing.None) 200f else 164f
        val t = textRun(title, TS.labelL(look.bold), textMax)
        val v = value?.takeIf { it.isNotEmpty() }?.let { textRun(it, TS.body26(look.bold), textMax) }
        onDrawBehind {
            val cy = size.height / 2f
            if (look.le) outlinePill(0f, 0f, 352f, size.height, sw = 2f) else drawRoundRect(Neutral.surface1, cornerRadius = CornerRadius(size.height / 2f))
            if (icon != null) drawIcon(icon, 48f, cy, 48f, look.variantText)
            drawRun(t, 84f, cy + if (v != null) -6f else 10f, titleColor)
            if (v != null) drawRun(v, 84f, cy + 26f, look.variantText)
            when (trailing) {
                Trailing.Swatch -> drawCircle(swatch ?: look.roles.accent, 12f, Offset(314f, cy))
                Trailing.SwitchOn, Trailing.SwitchOff -> {
                    val on = trailing == Trailing.SwitchOn
                    drawRoundRect(if (on) look.roles.accent else Neutral.surface3, Offset(260f, cy - 22f), Size(72f, 44f), CornerRadius(22f))
                    drawCircle(Neutral.onSurface, 18f, Offset(if (on) 310f else 282f, cy))
                }
                Trailing.Chevron -> drawIcon(Icons.chevronRight, 314f, cy, 28f, look.variantText)
                Trailing.Check -> drawIcon(Icons.check, 314f, cy, 36f, look.roles.accent)
                Trailing.None -> Unit
            }
        }
    }
}

/** preview rowPill: an outline pill (Clear history, Try again) w x h with centred 26/28 px text. */
@Composable
fun PillItem(modifier: Modifier, text: String, color: Color = Neutral.onSurfaceVariant, w: Int = 240, h: Int = 96, onClick: () -> Unit) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    DrawnItem(modifier, w, h, description = text, press = rowPress(look, w.toFloat(), h.toFloat(), haptics), onClick = onClick) {
        val t = textRun(text, TS.body26(look.bold).copy(font = OFont.G600.bumped(look.bold)), w - 40f)
        onDrawBehind {
            outlinePill(0f, 0f, size.width, size.height, sw = 2f)
            drawRun(t, size.width / 2f, size.height / 2f + 9f, color, TAlign.InkCenter)
        }
    }
}

/** rotates a chevron for list affordances; kept for pickers. */
fun DrawScope.chevronDown(cx: Float, cy: Float, color: Color) = rotate(90f, Offset(cx, cy)) { drawIcon(Icons.chevronRight, cx, cy, 28f, color) }

/** Empty-state block: icon + one line (Recent "Nothing yet", hidden apps "None hidden"). */
@Composable
fun EmptyItem(modifier: Modifier, icon: OIcon, text: String) {
    val look = LocalLook.current
    DrawnItem(modifier, 352, 140, description = text) {
        val t = textRun(text, TS.bodyL(look.bold), 330f)
        onDrawBehind {
            drawIcon(icon, 176f, 40f, 64f, Neutral.onSurfaceMuted)
            drawRun(t, 176f, 118f, look.variantText, TAlign.InkCenter)
        }
    }
}

/** Neutral glass key helper. */
fun glassKey(w: Int, h: Int, r: Float, v: GlassVariant, shadow: Boolean = false) = GlassKey(w, h, r, v, shadow = shadow)

fun DrawScope.glassAt(g: GlassImage, x: Float, y: Float, alpha: Float = 1f) = drawGlass(g, x, y, alpha)
