package com.deskdot.app.wear.design

import androidx.compose.animation.core.AnimationSpec
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Immutable

/** §2.1 durations, ms. */
object Dur {
    const val MICRO = 100
    const val SHORT = 150
    const val MEDIUM = 250
    const val LONG = 350
}

/** §2.2 easings. */
object Ease {
    val emphasizedDecel: Easing = CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)
    val emphasizedAccel: Easing = CubicBezierEasing(0.3f, 0f, 0.8f, 0.15f)
    val standard: Easing = CubicBezierEasing(0.2f, 0f, 0f, 1f)
    val standardDecel: Easing = CubicBezierEasing(0f, 0f, 0f, 1f)
    val standardAccel: Easing = CubicBezierEasing(0.3f, 0f, 1f, 1f)
}

enum class SpringToken(val damping: Float, val stiffness: Float) {
    SpatialFast(0.6f, 800f),
    SpatialDefault(0.8f, 380f),
    SpatialSlow(0.8f, 200f),
    EffectsFast(1f, 3800f),
    EffectsDefault(1f, 1600f),
    EffectsSlow(1f, 800f),
}

/**
 * The single place that decides how anything moves (§2.4, §2.6, §6):
 *  - Low Energy or reduced motion (animator scale 0): every transition is a cut.
 *  - Thermal Calm: every Wake animation becomes a 100 ms tween instead of a spring.
 *  - otherwise the §2 springs and tweens.
 */
@Immutable
data class MotionPolicy(val cut: Boolean, val calm: Boolean) {
    fun spring(t: SpringToken): AnimationSpec<Float> = when {
        cut -> snap()
        calm -> androidx.compose.animation.core.tween(Dur.MICRO, easing = Ease.standard)
        else -> spring(dampingRatio = t.damping, stiffness = t.stiffness)
    }

    fun tween(ms: Int, easing: Easing): AnimationSpec<Float> = when {
        cut -> snap()
        // fully qualified: the member tween() would otherwise call itself (StackOverflow, caught by the tests)
        calm -> androidx.compose.animation.core.tween(minOf(ms, Dur.MICRO), easing = easing)
        else -> androidx.compose.animation.core.tween(ms, easing = easing)
    }

    /** Duration actually used by a tween of [ms] (for stagger/hold arithmetic). */
    fun ms(ms: Int): Int = when {
        cut -> 0
        calm -> minOf(ms, Dur.MICRO)
        else -> ms
    }

    companion object {
        val Default = MotionPolicy(cut = false, calm = false)
    }
}
