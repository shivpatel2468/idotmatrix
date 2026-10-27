package com.deskdot.app.wear.ui

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.view.WindowManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.pager.PagerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.rotary.onRotaryScrollEvent
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.wear.input.RemoteInputIntentHelper
import com.deskdot.app.wear.design.LocalHaptics
import com.deskdot.app.wear.design.PageDots
import com.deskdot.app.wear.design.SuiteTimeText
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import android.app.RemoteInput as ARemoteInput

/** Screen chrome: content, then the curved TimeText (nothing behind it, rev 1.2) and optional page dots. */
@Composable
fun Screen(
    timeText: Boolean = true,
    pager: PagerState? = null,
    content: @Composable BoxScope.() -> Unit,
) {
    Box(Modifier.fillMaxSize()) {
        content()
        if (timeText) SuiteTimeText()
        if (pager != null) PageDots(pager)
    }
}

/**
 * §4.2.7 / owner rule 13: the crown target must hold focus whenever its screen is the visible one — on first
 * show, after returning from another screen and after the activity resumes (the system steals focus on pause).
 */
@Composable
fun FocusWhenActive(requester: FocusRequester, active: Boolean = true) {
    val lifecycle = LocalLifecycleOwner.current
    LaunchedEffect(lifecycle, active) {
        if (!active) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            // the first frame may not have attached the focus target yet
            repeat(3) {
                if (runCatching { requester.requestFocus() }.isSuccess) return@repeatOnLifecycle
                kotlinx.coroutines.delay(32)
            }
        }
    }
}

/**
 * Crown steps for fixed (non-list) screens: accumulates rotary pixels and calls [onStep] with ±1 once per
 * [stepPx] (one CLOCK_TICK per step is the caller's job, so it can REJECT at a limit instead).
 */
fun Modifier.crownSteps(requester: FocusRequester, stepPx: Float = 48f, onStep: (Int) -> Unit): Modifier {
    var acc = 0f
    return this
        .onRotaryScrollEvent { e ->
            acc += e.verticalScrollPixels
            while (acc >= stepPx) { acc -= stepPx; onStep(1) }
            while (acc <= -stepPx) { acc += stepPx; onStep(-1) }
            true
        }
        .focusRequester(requester)
        .focusable()
}

/** Text entry through the system's RemoteInput (voice / keyboard / handwriting), §4.4.2. */
@Composable
fun rememberTextInput(label: String, onText: (String) -> Unit): () -> Unit {
    val cb by rememberUpdatedState(onText)
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
        val data = res.data ?: return@rememberLauncherForActivityResult
        val text = ARemoteInput.getResultsFromIntent(data)?.getCharSequence(KEY_TEXT)?.toString()?.trim().orEmpty()
        if (text.isNotEmpty()) cb(text)
    }
    return remember(label) {
        {
            val intent = RemoteInputIntentHelper.createActionRemoteInputIntent()
            val ri = ARemoteInput.Builder(KEY_TEXT).setLabel(label).build()
            RemoteInputIntentHelper.putRemoteInputsExtra(intent, listOf(ri))
            runCatching { launcher.launch(intent) }
        }
    }
}

private const val KEY_TEXT = "text"

fun Context.findActivity(): Activity? {
    var c: Context? = this
    while (c is ContextWrapper) {
        if (c is Activity) return c
        c = c.baseContext
    }
    return null
}

/**
 * §5.5.3 I-18: full brightness + keep-screen-on while a QR is visible, dropped after [maxMs] (5 min, 2 in
 * Calm). Restored when the page leaves or the activity pauses. Returns true while the boost is active.
 */
@Composable
fun QrBrightness(enabled: Boolean, maxMs: Long, onTimeout: () -> Unit) {
    val ctx = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    val timeout by rememberUpdatedState(onTimeout)
    LaunchedEffect(enabled, lifecycle) {
        val act = ctx.findActivity() ?: return@LaunchedEffect
        if (!enabled) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            val w = act.window
            val lp = w.attributes
            val prev = lp.screenBrightness
            try {
                w.attributes = lp.apply { screenBrightness = 1f }
                w.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                kotlinx.coroutines.delay(maxMs)
                timeout()
                kotlinx.coroutines.awaitCancellation()
            } finally {
                w.attributes = w.attributes.apply { screenBrightness = prev }
                w.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }
    }
}

/** QR code for [text], ECC M, byte mode, as a 1-px-per-module bitmap (rendered once per text, §7.3). */
class QrImage(val image: ImageBitmap, val modules: Int)

fun encodeQr(text: String): QrImage? = try {
    val m = QRCodeWriter().encode(
        text, BarcodeFormat.QR_CODE, 0, 0,
        mapOf(EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M, EncodeHintType.MARGIN to 0, EncodeHintType.CHARACTER_SET to "UTF-8"),
    )
    val n = m.width
    val px = IntArray(n * n) { i -> if (m.get(i % n, i / n)) 0xFF000000.toInt() else 0xFFFFFFFF.toInt() }
    val bmp = android.graphics.Bitmap.createBitmap(px, n, n, android.graphics.Bitmap.Config.ARGB_8888)
    QrImage(bmp.asImageBitmap(), n)
} catch (t: Throwable) {
    null
}

/** Draws the §5.5.3 white plate (quiet zone 4 modules) with the QR centred on C, pixel-aligned, unfiltered. */
fun androidx.compose.ui.graphics.drawscope.DrawScope.drawQrPlate(qr: QrImage) {
    val n = qr.modules
    val m = (259 / (n + 8)).coerceIn(5, 7)
    val side = (n + 8) * m
    val o = Math.round(208f - side / 2f)
    drawRect(androidx.compose.ui.graphics.Color.White, androidx.compose.ui.geometry.Offset(o.toFloat(), o.toFloat()), androidx.compose.ui.geometry.Size(side.toFloat(), side.toFloat()))
    drawImage(
        qr.image, srcOffset = IntOffset.Zero, srcSize = IntSize(n, n),
        dstOffset = IntOffset(o + 4 * m, o + 4 * m), dstSize = IntSize(n * m, n * m),
        filterQuality = FilterQuality.None,
    )
}

/** For pager pages: true while [page] is the settled current page. */
fun PagerState.isActive(page: Int) = currentPage == page

@Composable
fun rememberHaptics() = LocalHaptics.current

/** A float that crown handlers write and draw lambdas read. */
class CrownValue(v: Float) {
    var value by mutableFloatStateOf(v)
}
