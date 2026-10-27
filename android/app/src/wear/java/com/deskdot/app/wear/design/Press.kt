package com.deskdot.app.wear.design

import androidx.compose.animation.core.Animatable
import androidx.compose.foundation.IndicationNodeFactory
import androidx.compose.foundation.interaction.InteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.runtime.Stable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.ContentDrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.node.DelegatableNode
import androidx.compose.ui.node.DrawModifierNode
import androidx.compose.ui.node.invalidateDraw
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Press feedback drawn by an Indication node: no recomposition, no extra layer.
 *  - Wake: the content scales to [scaleTo] on `spatial-fast` and a [fill] round-rect of
 *    [w] x [h] / [radius] (centred) is drawn over it (§4.2.3 rows: #FFF @ 8%, r-full, 0.97;
 *    §1.9 glass: #FFF @ 10%, 0.96 / 0.92 for toggles).
 *  - Low Energy: no motion; a [leOutline] 4 px outline (2 dp accent, §4.2.3) appears instantly.
 * Haptics: VIRTUAL_KEY on press-down when Haptics = Strong (§4.2.3).
 */
@Stable
class PressFeedback(
    private val w: Float,
    private val h: Float,
    private val radius: Float,
    private val scaleTo: Float,
    private val fill: Color,
    private val motion: MotionPolicy,
    private val leOutline: Color?,
    private val haptics: SuiteHaptics?,
) : IndicationNodeFactory {
    override fun create(interactionSource: InteractionSource): DelegatableNode =
        PressNode(interactionSource, w, h, radius, scaleTo, fill, motion, leOutline, haptics)

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is PressFeedback) return false
        return w == other.w && h == other.h && radius == other.radius && scaleTo == other.scaleTo &&
            fill == other.fill && motion == other.motion && leOutline == other.leOutline && haptics === other.haptics
    }

    override fun hashCode(): Int {
        var r = w.hashCode()
        r = 31 * r + h.hashCode()
        r = 31 * r + radius.hashCode()
        r = 31 * r + scaleTo.hashCode()
        r = 31 * r + fill.hashCode()
        r = 31 * r + motion.hashCode()
        r = 31 * r + (leOutline?.hashCode() ?: 0)
        return r
    }
}

private val LeOutlineStroke = Stroke(width = 4f)

private class PressNode(
    private val source: InteractionSource,
    private val w: Float,
    private val h: Float,
    private val radius: Float,
    private val scaleTo: Float,
    private val fill: Color,
    private val motion: MotionPolicy,
    private val leOutline: Color?,
    private val haptics: SuiteHaptics?,
) : Modifier.Node(), DrawModifierNode {
    private val progress = Animatable(0f)
    private var job: Job? = null

    override fun onAttach() {
        coroutineScope.launch {
            source.interactions.collect { i ->
                when (i) {
                    is PressInteraction.Press -> {
                        haptics?.key()
                        animate(1f)
                    }
                    is PressInteraction.Release, is PressInteraction.Cancel -> animate(0f)
                }
            }
        }
    }

    private fun animate(target: Float) {
        job?.cancel()
        job = coroutineScope.launch {
            if (leOutline != null || motion.cut) {
                progress.snapTo(target)
            } else {
                progress.animateTo(target, motion.spring(SpringToken.SpatialFast))
            }
            invalidateDraw()
        }
    }

    override fun ContentDrawScope.draw() {
        val p = progress.value
        if (p <= 0.001f) {
            drawContent()
            return
        }
        val cx = size.width / 2f
        val cy = size.height / 2f
        val tl = Offset(cx - w / 2f, cy - h / 2f)
        if (leOutline != null) {
            drawContent()
            drawRoundRect(leOutline, tl + Offset(2f, 2f), Size(w - 4f, h - 4f), CornerRadius(radius - 2f), style = LeOutlineStroke)
            return
        }
        val s = 1f + (scaleTo - 1f) * p
        scale(s, s, Offset(cx, cy)) {
            this@draw.drawContent()
            drawRoundRect(fill, tl, Size(w, h), CornerRadius(radius), alpha = p.coerceIn(0f, 1f))
        }
    }
}

/**
 * §1.13 on-press label timing: fade in + slide up 4 px over 120 ms (standard-decel) on press-down,
 * hold while pressed and 1200 ms after release, then fade out over 150 ms (standard-accel).
 * LE: instant in/out, same hold. Read [alpha]/[lift] in draw only.
 */
@Stable
class PressLabel {
    private val anim = Animatable(0f)
    private var hold: Job? = null
    val alpha: Float get() = anim.value
    val lift: Float get() = (1f - anim.value) * 4f

    suspend fun pressed(motion: MotionPolicy) {
        hold?.cancel()
        anim.animateTo(1f, motion.tween(120, Ease.standardDecel))
    }

    /** Call from a scope that outlives the release (e.g. the composable's scope). */
    fun released(scope: kotlinx.coroutines.CoroutineScope, motion: MotionPolicy) {
        hold?.cancel()
        hold = scope.launch {
            delay(1200)
            anim.animateTo(0f, motion.tween(150, Ease.standardAccel))
        }
    }

    /** Show briefly without a press (crown steps on the brightness capsule, crown focus). */
    fun flash(scope: kotlinx.coroutines.CoroutineScope, motion: MotionPolicy) {
        hold?.cancel()
        hold = scope.launch {
            anim.animateTo(1f, motion.tween(120, Ease.standardDecel))
            delay(1200)
            anim.animateTo(0f, motion.tween(150, Ease.standardAccel))
        }
    }
}

/** Drives a [PressLabel] from an interaction source (press-down shows, release starts the hold). */
@androidx.compose.runtime.Composable
fun rememberPressLabel(source: InteractionSource, motion: MotionPolicy): PressLabel {
    val label = androidx.compose.runtime.remember { PressLabel() }
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    androidx.compose.runtime.LaunchedEffect(source, motion) {
        source.interactions.collect { i ->
            when (i) {
                is PressInteraction.Press -> launch { label.pressed(motion) }
                is PressInteraction.Release, is PressInteraction.Cancel -> label.released(scope, motion)
            }
        }
    }
    return label
}
