package com.deskdot.app.wear.design

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

enum class SuiteMode { Wake, LowEnergy }

/**
 * Everything that changes how Suite looks, in one immutable value. It changes rarely (theme, Low
 * Energy, Calm, sun), so it is provided as a *static* local: a change is a deliberate full redraw,
 * and nothing in the tree subscribes to it per frame.
 */
@Immutable
data class SuiteLook(
    val mode: SuiteMode = SuiteMode.Wake,
    val roles: AccentRoles = AccentThemes.of(AccentId.Ember),
    val calm: Boolean = false,
    /** §6 sunlight boost (lux >= 20k sampled once on resume). */
    val sun: Boolean = false,
    val motion: MotionPolicy = MotionPolicy.Default,
) {
    val le: Boolean get() = mode == SuiteMode.LowEnergy

    /** +100 weight in Low Energy or sun boost (§4.1, §6). */
    val bold: Boolean get() = le || sun

    /** Secondary text: on-surface-variant, promoted to on-surface by sun boost (§6). */
    val variantText: Color get() = if (sun) Neutral.onSurface else Neutral.onSurfaceVariant

    /** Accent used for text: accent-light under sun boost (§6). */
    val accentText: Color get() = if (sun) roles.accentLight else roles.accent

    /** Text-bearing neutral glass: the sun-text variant under sun boost (§6). */
    val textGlass: GlassVariant get() = if (sun) GlassVariant.SunText else GlassVariant.NeutralText
}

val LocalLook = staticCompositionLocalOf { SuiteLook() }

@Composable
fun SuiteTheme(look: SuiteLook, content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalLook provides look, content = content)
}
