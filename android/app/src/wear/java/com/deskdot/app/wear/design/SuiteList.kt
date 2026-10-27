package com.deskdot.app.wear.design

import android.os.SystemClock
import androidx.compose.animation.core.exponentialDecay
import androidx.compose.animation.core.snap
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.LocalOverscrollConfiguration
import androidx.compose.foundation.focusable
import androidx.compose.foundation.gestures.FlingBehavior
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.gestures.snapping.SnapLayoutInfoProvider
import androidx.compose.foundation.gestures.snapping.SnapPosition
import androidx.compose.foundation.gestures.snapping.snapFlingBehavior
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.requiredHeight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListItemInfo
import androidx.compose.foundation.lazy.LazyListLayoutInfo
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.withFrameMillis
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.rotary.onPreRotaryScrollEvent
import androidx.compose.ui.input.rotary.onRotaryScrollEvent
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.rotary.RotaryScrollableDefaults
import androidx.wear.compose.foundation.rotary.RotarySnapLayoutInfoProvider
import androidx.wear.compose.foundation.rotary.rotaryScrollable
import kotlinx.coroutines.launch
import kotlin.math.abs
import kotlin.math.pow

/**
 * §4.2 reference fisheye, applied exactly (instead of approximating it with ScalingParams):
 * t = |d|/208, u = max(0, (t-0.18)/0.82), scale = 1 - 0.30 u^1.7, alpha = 1 - 0.60 u^2 (LE 0.50).
 *
 * Items are also *packed* the way the preview packs them: a row that shrinks takes less space.
 * The preview packs from a centred anchor row, which jumps whenever the anchor changes; here the
 * same packing is expressed as one continuous mapping from a natural (unscaled) position to a
 * visual position, dv/dx = scale(v), integrated once into a lookup table. At rest this lands
 * within ~2 px of the preview, and it is perfectly continuous while scrolling.
 */
object Fisheye {
    fun scale(d: Float): Float {
        val t = (abs(d) / 208f).coerceAtMost(1f)
        val u = ((t - 0.18f) / 0.82f).coerceAtLeast(0f)
        return 1f - 0.30f * u.pow(1.7f)
    }

    fun alpha(d: Float, lowEnergy: Boolean): Float {
        val t = (abs(d) / 208f).coerceAtMost(1f)
        val u = ((t - 0.18f) / 0.82f).coerceAtLeast(0f)
        return if (lowEnergy) maxOf(0.5f, 1f - 0.5f * u * u) else maxOf(0.4f, 1f - 0.6f * u * u)
    }

    private const val R = 720
    private val lut = FloatArray(2 * R + 1).also { t ->
        var v = 0f
        for (i in 1..R) {
            val k1 = scale(v)
            v += scale(v + 0.5f * k1)
            t[R + i] = v
            t[R - i] = -v
        }
    }

    /** Visual offset from C of something whose natural offset from C is [x]. */
    fun visual(x: Float): Float {
        if (x >= R) return lut[2 * R] + (x - R) * 0.7f
        if (x <= -R) return lut[0] + (x + R) * 0.7f
        val fx = x + R
        val i = fx.toInt()
        val f = fx - i
        return lut[i] + (lut[i + 1] - lut[i]) * f
    }
}

/** List state: a LazyListState plus the fisheye geometry everyone (lens, haptics, menus) agrees on. */
@Stable
class SuiteListState(initialIndex: Int = 0) {
    val lazy = LazyListState(firstVisibleItemIndex = initialIndex)

    /** Extra composed height above and below the screen so rows pulled in by the fisheye exist. */
    internal val extendPx: Int = 128

    internal var lowEnergy by mutableStateOf(false)

    /** Open-stagger clock (§4.2.6), ms since the open began; >= OPEN_DONE when idle. */
    internal var openMs by mutableFloatStateOf(OPEN_DONE)

    /** Uptime of the last crown event, so index changes can be attributed to the crown. */
    internal var lastRotaryAt = 0L

    fun naturalCentre(info: LazyListItemInfo, li: LazyListLayoutInfo): Float =
        (info.offset - li.viewportStartOffset - extendPx).toFloat() + info.size / 2f

    private fun centreInfo(): LazyListItemInfo? {
        val li = lazy.layoutInfo
        val items = li.visibleItemsInfo
        var best: LazyListItemInfo? = null
        var bestD = Float.MAX_VALUE
        for (i in items.indices) {
            val it = items[i]
            val d = abs(naturalCentre(it, li) - Geometry.C)
            if (d < bestD) {
                bestD = d
                best = it
            }
        }
        return best
    }

    /** Index of the item whose centre is nearest the screen centre (-1 while empty). */
    val centerIndex: Int by derivedStateOf { centreInfo()?.index ?: -1 }

    /** Natural distance (px) of the centre item from C; 0 when snapped. */
    fun centerOffset(): Float {
        val li = lazy.layoutInfo
        val info = centreInfo() ?: return 0f
        return naturalCentre(info, li) - Geometry.C
    }

    /** §4.2.8: an item counts as snapped while its centre is within ±8 px of C. */
    val snappedIndex: Int by derivedStateOf {
        val li = lazy.layoutInfo
        val info = centreInfo()
        if (info != null && abs(naturalCentre(info, li) - Geometry.C) <= 8f) info.index else -1
    }

    /** Visual centre y (screen px) and fisheye scale of item [index], or null if not composed. */
    fun visualOf(index: Int): Pair<Float, Float>? {
        val li = lazy.layoutInfo
        val items = li.visibleItemsInfo
        for (i in items.indices) {
            val it = items[i]
            if (it.index == index) {
                val d = Fisheye.visual(naturalCentre(it, li) - Geometry.C)
                return (Geometry.C + d) to Fisheye.scale(d)
            }
        }
        return null
    }

    /** Scroll so item [index] is centred (clamped by the R1 padding at the ends). */
    suspend fun animateToCentre(index: Int) {
        val li = lazy.layoutInfo
        val info = li.visibleItemsInfo.firstOrNull { it.index == index }
        if (info != null) {
            lazy.animateScrollBy(naturalCentre(info, li) - Geometry.C)
        } else {
            lazy.scrollToItem(index)
            val l2 = lazy.layoutInfo
            l2.visibleItemsInfo.firstOrNull { it.index == index }?.let { lazy.scrollBy(naturalCentre(it, l2) - Geometry.C) }
        }
    }

    suspend fun jumpToTop() {
        lazy.scrollToItem(0, 0)
    }

    /** §4.2.6: replay the open stagger. */
    suspend fun playOpen(motion: MotionPolicy) {
        if (motion.cut) {
            openMs = OPEN_DONE
            return
        }
        val span = if (motion.calm) 100f else 250f
        val start = withFrameMillis { it }
        openMs = 0f
        while (true) {
            val t = (withFrameMillis { it } - start).toFloat() * (250f / span)
            openMs = t
            if (t >= OPEN_DONE) break
        }
        openMs = OPEN_DONE
    }

    companion object {
        const val OPEN_DONE = 4 * 30f + 250f + 1f
    }
}

@Composable
fun rememberSuiteListState(initialIndex: Int = 0) = remember { SuiteListState(initialIndex) }

/** Per-item transform: fisheye scale, packing, alpha and the open stagger. Draw-phase only. */
internal fun Modifier.fisheyeItem(state: SuiteListState, index: Int): Modifier = this.graphicsLayer {
    val li = state.lazy.layoutInfo
    val items = li.visibleItemsInfo
    var info: LazyListItemInfo? = null
    for (i in items.indices) {
        val it = items[i]
        if (it.index == index) {
            info = it
            break
        }
    }
    if (info == null) return@graphicsLayer
    val nat = state.naturalCentre(info, li)
    val d = Fisheye.visual(nat - Geometry.C)
    var s = Fisheye.scale(d)
    var a = Fisheye.alpha(d, state.lowEnergy)
    var ty = Geometry.C + d - nat
    val om = state.openMs
    if (om < SuiteListState.OPEN_DONE && index < 5) {
        val p = ((om - index * 30f) / 250f).coerceIn(0f, 1f)
        val e = Ease.emphasizedDecel.transform(p)
        a *= e
        s *= 0.92f + 0.08f * e
        ty += 32f * (1f - e)
    }
    scaleX = s
    scaleY = s
    translationY = ty
    alpha = a
    // Per-op alpha: never an offscreen buffer per row (§2.5 / overdraw budget).
    compositingStrategy = CompositingStrategy.ModulateAlpha
}

/** Item DSL that hands every item its fisheye modifier (which must be the outermost modifier). */
class SuiteListScope internal constructor(private val scope: LazyListScope, private val state: SuiteListState) {
    private var next = 0

    val count: Int get() = next

    fun item(key: Any? = null, contentType: Any? = null, content: @Composable (Modifier) -> Unit) {
        val index = next++
        scope.item(key, contentType) { content(Modifier.fisheyeItem(state, index)) }
    }

    fun <T> items(
        list: List<T>,
        key: ((T) -> Any)? = null,
        contentType: Any? = null,
        content: @Composable (T, Modifier) -> Unit,
    ) {
        val base = next
        next += list.size
        scope.items(
            count = list.size,
            key = if (key != null) { i: Int -> key(list[i]) } else null,
            contentType = { contentType },
        ) { i -> content(list[i], Modifier.fisheyeItem(state, base + i)) }
    }
}

/** §4.2.8: alpha mask on the scrolling content only — nothing is ever drawn behind the clock. */
fun Modifier.edgeFade(): Modifier = this
    .graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }
    .drawWithCache {
        val h = size.height
        val brush = Brush.verticalGradient(
            0f to Color.Transparent,
            (36f / 416f) to Color.Transparent,
            (92f / 416f) to Color.Black,
            (340f / 416f) to Color.Black,
            (396f / 416f) to Color.Transparent,
            1f to Color.Transparent,
            startY = 0f,
            endY = h,
        )
        onDrawWithContent {
            drawContent()
            drawRect(brush, blendMode = BlendMode.DstIn)
        }
    }

private class CentreSnapProvider(private val s: SuiteListState) : RotarySnapLayoutInfoProvider {
    override val averageItemSize: Float
        get() {
            val items = s.lazy.layoutInfo.visibleItemsInfo
            if (items.isEmpty()) return 104f
            var sum = 0
            for (i in items.indices) sum += items[i].size
            return sum.toFloat() / items.size + 8f
        }
    override val currentItemIndex: Int get() = s.centerIndex.coerceAtLeast(0)
    override val currentItemOffset: Float get() = -s.centerOffset()
    override val totalItemCount: Int get() = s.lazy.layoutInfo.totalItemsCount
}

/** Snap so the nearest item centre lands on screen y 208 (the screen centre, not the padded centre). */
private val CentreSnapPosition = object : SnapPosition {
    override fun position(
        layoutSize: Int,
        itemSize: Int,
        beforeContentPadding: Int,
        afterContentPadding: Int,
        itemIndex: Int,
        itemCount: Int,
    ): Int = layoutSize / 2 - beforeContentPadding - itemSize / 2
}

@Composable
private fun rememberSuiteFling(state: SuiteListState, lowEnergy: Boolean): FlingBehavior {
    val density = LocalDensity.current
    return remember(state, lowEnergy, density) {
        val base = SnapLayoutInfoProvider(state.lazy, CentreSnapPosition)
        if (lowEnergy) {
            // §2.4 LE: no fling decay — snap to the nearest item, instantly.
            val nearest = object : SnapLayoutInfoProvider {
                override fun calculateApproachOffset(velocity: Float, decayOffset: Float): Float = 0f
                override fun calculateSnapOffset(velocity: Float): Float = base.calculateSnapOffset(0f)
            }
            snapFlingBehavior(nearest, exponentialDecay<Float>(), snap())
        } else {
            snapFlingBehavior(base, exponentialDecay(frictionMultiplier = 1.4f), androidx.compose.animation.core.spring(stiffness = 500f))
        }
    }
}

/**
 * The one list used by every scrolling screen (Home, Recent, Settings, About, Search, pickers):
 *  - R1 padding: first item top at y 92 at rest, last item bottom at y 340 at the end (§4.2.8);
 *  - fisheye per the §4.2 reference curve; edge fade as an alpha mask on this container only;
 *  - centre snapping for touch flings and the crown; in LE both snap instantly;
 *  - crown: Suite's own CLOCK_TICK per centred-index change, REJECT once at either end.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SuiteList(
    state: SuiteListState,
    focusRequester: FocusRequester,
    modifier: Modifier = Modifier,
    /** Drawn inside the faded layer, under the rows (the lens, §4.2.4). */
    under: (DrawScope.() -> Unit)? = null,
    /** §4.4.1 velocity trigger: called once when the crown moves >= 6 items within 300 ms. */
    onFastCrown: (() -> Unit)? = null,
    content: SuiteListScope.() -> Unit,
) {
    val look = LocalLook.current
    val haptics = LocalHaptics.current
    val density = LocalDensity.current
    val le = look.le
    SideEffect { state.lowEnergy = le }

    val fastCrown by rememberUpdatedState(onFastCrown)
    LaunchedEffect(state) {
        var last = state.centerIndex
        val stamps = LongArray(6)
        var n = 0
        snapshotFlow { state.centerIndex }.collect { idx ->
            if (idx >= 0 && idx != last) {
                val now = SystemClock.uptimeMillis()
                if (now - state.lastRotaryAt < 350) {
                    haptics.tick()
                    stamps[n % 6] = now
                    n++
                    // stamps[n % 6] is now the oldest of the last six crown-driven steps.
                    if (n >= 6 && now - stamps[n % 6] <= 300) {
                        n = 0
                        fastCrown?.invoke()
                    }
                } else {
                    n = 0
                }
                last = idx
            }
        }
    }

    val scope = rememberCoroutineScope()
    var lastRejectAt by remember { mutableStateOf(0L) }
    var leAccum by remember { mutableFloatStateOf(0f) }

    val rotary: Modifier = if (le) {
        // LE crown: 1 item per ~1.5 rows of rotary travel, moved instantly (no animation, §2.4).
        Modifier
            .onRotaryScrollEvent { e ->
                leAccum += e.verticalScrollPixels
                val step = 64f
                if (abs(leAccum) >= step) {
                    val dir = if (leAccum > 0) 1 else -1
                    leAccum = 0f
                    val target = (state.centerIndex + dir).coerceIn(0, (state.lazy.layoutInfo.totalItemsCount - 1).coerceAtLeast(0))
                    scope.launch { state.animateToCentreInstant(target) }
                }
                true
            }
            .focusRequester(focusRequester)
            .focusable()
    } else {
        Modifier.rotaryScrollable(
            behavior = RotaryScrollableDefaults.snapBehavior(
                scrollableState = state.lazy,
                layoutInfoProvider = remember(state) { CentreSnapProvider(state) },
                hapticFeedbackEnabled = false,
            ),
            focusRequester = focusRequester,
        )
    }

    val ext = state.extendPx
    val topPad = with(density) { (Geometry.READ_TOP + ext).toDp() }
    val bottomPad = with(density) { (Geometry.SCREEN - Geometry.READ_BOTTOM + ext).toDp() }
    val height = with(density) { (Geometry.SCREEN + 2 * ext).toDp() }

    Box(
        modifier = modifier
            .fillMaxSize()
            .onPreRotaryScrollEvent { e ->
                val now = SystemClock.uptimeMillis()
                if (now - state.lastRotaryAt > 300) {
                    val blocked = if (e.verticalScrollPixels > 0) !state.lazy.canScrollForward else !state.lazy.canScrollBackward
                    if (blocked && now - lastRejectAt > 600) {
                        lastRejectAt = now
                        haptics.reject()
                    }
                }
                state.lastRotaryAt = now
                false
            }
            .edgeFade()
            .then(if (under != null) Modifier.drawBehind(under) else Modifier),
        contentAlignment = Alignment.Center,
    ) {
        CompositionLocalProvider(LocalOverscrollConfiguration provides null) {
            LazyColumn(
                state = state.lazy,
                modifier = Modifier
                    .fillMaxWidth()
                    .requiredHeight(height)
                    .then(rotary),
                contentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = topPad, bottom = bottomPad),
                verticalArrangement = Arrangement.spacedBy(4.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                flingBehavior = rememberSuiteFling(state, le),
            ) {
                SuiteListScope(this, state).content()
            }
        }
    }
}

/** LE: centre [index] with no animation. */
internal suspend fun SuiteListState.animateToCentreInstant(index: Int) {
    val li = lazy.layoutInfo
    val info = li.visibleItemsInfo.firstOrNull { it.index == index }
    if (info != null) {
        lazy.scrollBy(naturalCentre(info, li) - Geometry.C)
    } else {
        lazy.scrollToItem(index)
    }
}
