package com.deskdot.app

import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.view.View
import android.view.animation.DecelerateInterpolator
import android.view.animation.LinearInterpolator
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin

/**
 * The app's intro: the DeskDot logo builds itself out of LED dots on a faint strip of the panel's matrix, like the
 * panel does — the "D" drops in, "esk" types in, "Dot" rains down (the same choreography and glyphs as the studio's
 * logo, web/src/lib/logo.ts) — then the tubes strike once and stay lit. About 1.4 s at normal animation speed.
 *
 * - Animator-driven, so Android's animation-duration scale applies; with animations off it draws the lit logo at once.
 * - If the studio isn't ready when the logo is built, the lit logo waits with a very slow, faint shimmer (no text).
 * - [finish] fades it out and hands over (≈ 0.3 s); the caller removes the view at the end.
 * Nothing loops once it has handed over.
 */
class IntroView(context: Context, private val page: Int, private val light: Boolean) : View(context) {
    private data class Dot(val x: Int, val y: Int, val part: Int, val col: Float, val seed: Float)

    private val dots = ArrayList<Dot>()
    private var cols = 0
    private val rows = 7
    private val tubes: IntArray =
        if (light) intArrayOf(0xFFC2154D.toInt(), 0xFFC2154D.toInt(), 0xFF996300.toInt())
        else intArrayOf(0xFFFF3F78.toInt(), 0xFFFF3F78.toInt(), 0xFFFFCC33.toInt())
    private val unlit = if (light) Color.argb(33, 74, 58, 36) else Color.argb(14, 255, 255, 255)
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val glows = arrayOfNulls<Bitmap>(3)
    private var glowFor = 0f

    /** Build progress in seconds of the 1.4 s timeline (scaled by the system's animation speed via the animator). */
    private var t = 0f
    private var shimmer = -1f // 0..1 while waiting, -1 off
    private var exit = 0f // 0..1 while handing over
    private var built = false
    private var finishing = false
    private var onGone: (() -> Unit)? = null
    private val animated = ValueAnimator.areAnimatorsEnabled()
    private var build: ValueAnimator? = null
    private var wait: ValueAnimator? = null

    init {
        // the same 7-row glyphs as web/src/lib/logo.ts: "D" · "esk" · "Dot", one dot between letters, one between tubes
        val glyphs = mapOf(
            'D' to listOf("###.", "#..#", "#..#", "#..#", "#..#", "#..#", "###."),
            'e' to listOf("....", "....", ".##.", "#..#", "####", "#...", ".###"),
            's' to listOf("....", "....", ".###", "#...", ".##.", "...#", "###."),
            'k' to listOf("#...", "#...", "#..#", "#.#.", "##..", "#.#.", "#..#"),
            'o' to listOf("....", "....", ".##.", "#..#", "#..#", "#..#", ".##."),
            't' to listOf("...", ".#.", "###", ".#.", ".#.", ".#.", "..#"),
        )
        val rnd = java.util.Random(7)
        var x = 0
        listOf("D", "esk", "Dot").forEachIndexed { part, word ->
            if (part > 0) x += 1
            val from = x
            val start = dots.size
            word.forEachIndexed { i, ch ->
                val g = glyphs.getValue(ch)
                if (i > 0) x += 1
                g.forEachIndexed { y, row -> row.forEachIndexed { dx, c -> if (c == '#') dots.add(Dot(x + dx, y, part, 0f, rnd.nextFloat())) } }
                x += g[0].length
            }
            val span = max(1, x - from - 1).toFloat()
            for (i in start until dots.size) dots[i] = dots[i].copy(col = (dots[i].x - from) / span)
        }
        cols = x
        setBackgroundColor(page)
        isClickable = true // the studio underneath stays untouchable until the hand-over
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES
        contentDescription = "DeskDot"
    }

    /** Play the build (or show the lit logo at once when animations are off). */
    fun start() {
        if (!animated) {
            t = BUILD
            built = true
            invalidate()
            return
        }
        build = ValueAnimator.ofFloat(0f, BUILD).apply {
            duration = (BUILD * 1000).toLong()
            interpolator = LinearInterpolator()
            addUpdateListener { t = it.animatedValue as Float; invalidate() }
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    built = true
                    if (finishing) fadeOut() else startShimmer()
                }
            })
            start()
        }
    }

    /** The studio is ready: hand over as soon as the logo is built. */
    fun finish(gone: () -> Unit) {
        onGone = gone
        if (finishing) return
        finishing = true
        if (built) fadeOut()
    }

    /** An error is shown under the logo: stop the shimmer, keep the logo lit. */
    fun hold() {
        wait?.cancel()
        wait = null
        shimmer = -1f
        invalidate()
    }

    private fun startShimmer() {
        if (!animated || finishing) return
        wait = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = 2400
            repeatCount = ValueAnimator.INFINITE
            interpolator = LinearInterpolator()
            addUpdateListener { shimmer = it.animatedValue as Float; invalidate() }
            start()
        }
    }

    private fun fadeOut() {
        wait?.cancel()
        wait = null
        shimmer = -1f
        if (!animated) {
            onGone?.invoke()
            return
        }
        ValueAnimator.ofFloat(0f, 1f).apply {
            duration = 320
            interpolator = DecelerateInterpolator(1.6f)
            addUpdateListener {
                exit = it.animatedValue as Float
                alpha = 1f - exit
                invalidate()
            }
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: Animator) {
                    onGone?.invoke()
                }
            })
            start()
        }
    }

    override fun onDetachedFromWindow() {
        build?.cancel()
        wait?.cancel()
        super.onDetachedFromWindow()
    }

    private fun glow(part: Int, size: Float): Bitmap {
        if (glowFor != size) {
            glows.fill(null)
            glowFor = size
        }
        return glows[part] ?: run {
            val s = max(4, size.toInt())
            val b = Bitmap.createBitmap(s, s, Bitmap.Config.ARGB_8888)
            val c = tubes[part]
            val a = if (light) 0.32f else 0.55f
            val p = Paint(Paint.ANTI_ALIAS_FLAG)
            p.shader = RadialGradient(
                s / 2f, s / 2f, s / 2f,
                intArrayOf(withAlpha(c, a), withAlpha(c, a * 0.35f), withAlpha(c, 0f)),
                floatArrayOf(0f, 0.4f, 1f), Shader.TileMode.CLAMP,
            )
            Canvas(b).drawCircle(s / 2f, s / 2f, s / 2f, p)
            b.also { glows[part] = it }
        }
    }

    override fun onDraw(canvas: Canvas) {
        // compact: the matrix strip is at most ~64 % of the width and 300 dp
        val dp = resources.displayMetrics.density
        val gridCols = cols + 4
        val gridRows = rows + 4
        val pitch = min(width * 0.64f, 300 * dp) / gridCols
        val r = pitch * 0.36f
        val ox = (width - gridCols * pitch) / 2f + 2 * pitch
        val oy = height * 0.46f - gridRows * pitch / 2f + 2 * pitch
        val zoom = 1f + exit * 0.08f
        canvas.save()
        canvas.scale(zoom, zoom, width / 2f, height * 0.46f)

        // the unlit matrix strip fades in first
        paint.color = unlit
        paint.alpha = (Color.alpha(unlit) * min(1f, t / 0.2f)).toInt()
        for (gy in 0 until gridRows) for (gx in 0 until gridCols) {
            canvas.drawCircle(ox + (gx - 2 + 0.5f) * pitch, oy + (gy - 2 + 0.5f) * pitch, r, paint)
        }

        // one strike: a quick flash as the logo completes, then steady
        val strike = when {
            t < BUILD - 0.25f -> 0.82f
            t < BUILD - 0.18f -> 1.15f
            t < BUILD - 0.12f -> 0.55f
            t < BUILD - 0.04f -> 1.1f
            else -> 1f
        }
        val g = pitch * 3.1f
        for (d in dots) {
            var x = d.x.toFloat()
            var y = d.y.toFloat()
            val k: Float
            var pop = 0f
            when (d.part) {
                0 -> { // the D drops in, bottom row first
                    k = clamp((t - (6 - d.y) * 0.035f) / 0.42f)
                    y -= (1 - bounce(k)) * 9
                }
                1 -> { // "esk" types in from the left
                    k = clamp((t - (0.12f + d.col * 0.62f + d.y * 0.01f)) / 0.2f)
                    pop = if (k > 0 && k < 1) sin(k * Math.PI).toFloat() else 0f
                    x -= (1 - easeOut(k)) * 1.2f
                }
                else -> { // "Dot" rains down
                    k = clamp((t - (0.2f + (1 - d.col) * 0.42f + d.seed * 0.22f)) / 0.45f)
                    y -= (1 - bounce(k)) * (6 + d.y)
                }
            }
            if (k <= 0f) continue
            val cx = ox + (x + 0.5f) * pitch
            val cy = oy + (y + 0.5f) * pitch
            // the slow shimmer: a soft band of light sliding across while the studio gets ready
            var lv = strike * min(1f, k * 1.6f)
            if (shimmer >= 0f) {
                val band = d.x / cols.toFloat() - (shimmer * 1.6f - 0.3f)
                lv *= 1f + 0.16f * kotlin.math.exp(-(band * band) / 0.012f)
            }
            val gb = glow(d.part, g)
            paint.alpha = (255 * min(1f, lv * 0.85f)).toInt()
            canvas.drawBitmap(gb, cx - gb.width / 2f, cy - gb.height / 2f, paint)
            paint.color = tubes[d.part]
            paint.alpha = (255 * min(1f, lv)).toInt()
            canvas.drawCircle(cx, cy, r * (1 + pop * 0.5f), paint)
            if (!light && lv > 0.7f) { // the hot core
                paint.color = Color.argb((90 * min(1f, lv)).toInt(), 255, 244, 224)
                canvas.drawCircle(cx, cy, r * 0.42f, paint)
            }
        }
        canvas.restore()
    }

    companion object {
        /** The build's length at normal animation speed (seconds): dots in by ~1.15 s, then the strike. */
        const val BUILD = 1.4f

        private fun clamp(v: Float) = max(0f, min(1f, v))
        private fun easeOut(k: Float) = 1 - (1 - k).pow(3)
        private fun bounce(k0: Float): Float {
            var k = k0
            val n = 7.5625f
            val d = 2.75f
            return when {
                k < 1 / d -> n * k * k
                k < 2 / d -> { k -= 1.5f / d; n * k * k + 0.75f }
                k < 2.5f / d -> { k -= 2.25f / d; n * k * k + 0.9375f }
                else -> { k -= 2.625f / d; n * k * k + 0.984375f }
            }
        }
        private fun withAlpha(c: Int, a: Float) = Color.argb((255 * a).toInt().coerceIn(0, 255), Color.red(c), Color.green(c), Color.blue(c))
    }
}
