package com.deskdot.app.wear.design

import android.os.SystemClock
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.compose.runtime.staticCompositionLocalOf

enum class HapticsLevel(val title: String) { Off("Off"), Subtle("Subtle"), Strong("Strong") }

/**
 * §4.2.7 / §4.9 haptics. Wear OS 3 adds no crown haptics in third-party lists (owner decision 5),
 * so Suite plays its own CLOCK_TICK per crown step. Gating:
 *  - tick: Crown ticks switch AND Haptics != Off, throttled to >= 35 ms;
 *  - reject / longPress / confirm: Haptics != Off (Subtle = long-press and confirm only);
 *  - launch (CONFIRM on app launch) and key (VIRTUAL_KEY on press): Strong only.
 */
class SuiteHaptics(private val view: View) {
    @Volatile var level: HapticsLevel = HapticsLevel.Subtle
    @Volatile var crownTicks: Boolean = true
    private var lastTickAt = 0L

    fun tick() {
        if (level == HapticsLevel.Off || !crownTicks) return
        val now = SystemClock.uptimeMillis()
        if (now - lastTickAt < 35) return
        lastTickAt = now
        view.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK)
    }

    fun reject() {
        if (level != HapticsLevel.Off) view.performHapticFeedback(HapticFeedbackConstants.REJECT)
    }

    fun confirm() {
        if (level != HapticsLevel.Off) view.performHapticFeedback(HapticFeedbackConstants.CONFIRM)
    }

    fun longPress() {
        if (level != HapticsLevel.Off) view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
    }

    fun launch() {
        if (level == HapticsLevel.Strong) view.performHapticFeedback(HapticFeedbackConstants.CONFIRM)
    }

    fun key() {
        if (level == HapticsLevel.Strong) view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
    }
}

val LocalHaptics = staticCompositionLocalOf<SuiteHaptics> { error("SuiteHaptics not provided") }
