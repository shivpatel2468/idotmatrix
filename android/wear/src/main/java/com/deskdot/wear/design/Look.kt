package com.deskdot.wear.design

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.AnimationVector1D
import androidx.compose.animation.core.spring
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.deskdot.wear.theme.WatchPalette
import com.deskdot.wear.theme.WatchThemes

/**
 * The table the watch wears, dark (OLED black) or light (porcelain), and the glass baked in its colours. Read with
 * [LocalLook]; every glass element comes from [GlassFactory] (baked once, one drawImage at runtime).
 */
@Immutable
class Look(val table: String = WatchThemes.DEFAULT, val dark: Boolean = true) {
    val p: WatchPalette = WatchThemes.get(table).palette(dark)
    val bg: Color = if (dark) Color.Black else Color(p.chassis1)
    val ink1 = Color(p.ink1)
    val ink2 = Color(p.ink2)
    val ink3 = Color(p.ink3)
    val accent = Color(p.accent)
    /** Icons on "on" glass: the accent, lifted towards white in the dark so it reads on accent-deep glass. */
    val accentLight = if (dark) Color(p.accent2) else Color(p.accent)

    fun glass(w: Int, h: Int, r: Float, v: GlassVariant, shadow: Boolean = false) = GlassKey(w, h, r, v, table, dark, shadow)

    override fun equals(other: Any?) = other is Look && other.table == table && other.dark == dark
    override fun hashCode() = table.hashCode() * 31 + dark.hashCode()
}

val LocalLook = staticCompositionLocalOf { Look() }

private val PressIn = spring<Float>(dampingRatio = 0.7f, stiffness = 1400f)
private val Jelly = spring<Float>(dampingRatio = 0.28f, stiffness = 420f)

/** Orbit's jelly press: 0 at rest, up to 1 while pressed, and on release it springs back past 0 a few times. */
@Composable
fun rememberWobble(pressed: Boolean): Animatable<Float, AnimationVector1D> {
    val w = remember { Animatable(0f) }
    LaunchedEffect(pressed) { w.animateTo(if (pressed) 1f else 0f, if (pressed) PressIn else Jelly) }
    return w
}

/** Squash on press, then a volume-keeping jelly wobble ([amount] 1 = Orbit's round buttons; rows use less). */
fun Modifier.wobble(w: Animatable<Float, AnimationVector1D>, amount: Float = 1f): Modifier = graphicsLayer {
    val v = w.value * amount
    scaleX = 1f - 0.10f * v + 0.04f * v * v
    scaleY = 1f - 0.16f * v
}

/** Size of the row slot and of the glass pill inside it (the gap between pills is the difference). */
val RowSlot = 58.dp
val PillW = 176.dp
val PillH = 50.dp

/**
 * A list row as Orbit's Workout list draws it: a baked glass capsule, the [icon] in an accent-tinted glass disc on
 * the left, a title and a plain-words line under it. Pressing squashes it like jelly.
 */
@Composable
fun GlassRow(icon: WIcon?, title: String, sub: String?, onClick: () -> Unit) {
    val look = LocalLook.current
    val src = remember { MutableInteractionSource() }
    val pressed by src.collectIsPressedAsState()
    val wob = rememberWobble(pressed)
    Box(Modifier.fillMaxWidth().height(RowSlot), contentAlignment = Alignment.Center) {
        Box(
            Modifier
                .size(PillW, PillH)
                .semantics { contentDescription = listOfNotNull(title, sub).joinToString(", ") }
                .clickable(interactionSource = src, indication = null, role = Role.Button, onClick = onClick)
                .wobble(wob, 0.45f)
                .drawWithCache {
                    val w = size.width.toInt()
                    val h = size.height.toInt()
                    val row = GlassFactory.get(look.glass(w, h, h / 2f, GlassVariant.NeutralText))
                    val d = (h * 0.62f).toInt()
                    val disc = if (icon != null) GlassFactory.get(look.glass(d, d, d / 2f, GlassVariant.On)) else null
                    onDrawBehind {
                        drawGlass(row, 0f, 0f)
                        if (icon != null && disc != null) {
                            val cx = h / 2f
                            drawGlass(disc, cx - d / 2f, h / 2f - d / 2f)
                            drawIcon(icon, cx, h / 2f, d * 0.56f, look.accentLight)
                        }
                    }
                },
            contentAlignment = Alignment.CenterStart,
        ) {
            Column(Modifier.padding(start = if (icon != null) 46.dp else 20.dp, end = 16.dp)) {
                BasicText(title, style = TextStyle(look.ink1, 15.sp, FontWeight.SemiBold), maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (!sub.isNullOrEmpty()) BasicText(sub, style = TextStyle(look.ink3, 11.sp), maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** A round glass button with Orbit's jelly press: [variant] Neutral for most, On for the main action. */
@Composable
fun GlassButton(icon: WIcon, label: String, diameter: Dp, onClick: () -> Unit, modifier: Modifier = Modifier, variant: GlassVariant = GlassVariant.Neutral) {
    val look = LocalLook.current
    val src = remember { MutableInteractionSource() }
    val pressed by src.collectIsPressedAsState()
    val wob = rememberWobble(pressed)
    Box(
        modifier
            .size(diameter)
            .semantics { contentDescription = label }
            .clickable(interactionSource = src, indication = null, role = Role.Button, onClick = onClick)
            .wobble(wob)
            .drawWithCache {
                val d = size.width.toInt()
                val g = GlassFactory.get(look.glass(d, d, d / 2f, variant))
                val tint = if (variant == GlassVariant.On) look.accentLight else look.ink2
                onDrawBehind {
                    drawGlass(g, 0f, 0f)
                    drawIcon(icon, d / 2f, d / 2f, d * 0.46f, tint)
                }
            },
    )
}
