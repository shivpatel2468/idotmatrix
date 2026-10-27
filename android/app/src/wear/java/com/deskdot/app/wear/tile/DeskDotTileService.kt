package com.deskdot.app.wear.tile

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import androidx.concurrent.futures.CallbackToFutureAdapter
import androidx.wear.protolayout.ActionBuilders
import androidx.wear.protolayout.ColorBuilders.argb
import androidx.wear.protolayout.DimensionBuilders.dp
import androidx.wear.protolayout.DimensionBuilders.expand
import androidx.wear.protolayout.DimensionBuilders.sp
import androidx.wear.protolayout.LayoutElementBuilders
import androidx.wear.protolayout.ModifiersBuilders
import androidx.wear.protolayout.ResourceBuilders
import androidx.wear.protolayout.TimelineBuilders
import androidx.wear.tiles.RequestBuilders
import androidx.wear.tiles.TileBuilders
import androidx.wear.tiles.TileService
import com.deskdot.app.wear.Dd
import com.deskdot.app.wear.data.SuiteSignalSource
import com.deskdot.app.wear.data.SuiteSignals
import com.deskdot.app.wear.design.AccentThemes
import androidx.compose.ui.graphics.toArgb
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.nio.ByteBuffer

/**
 * §5.12 DeskDot Tile: "DeskDot" (accent), the last panel frame as an 88 x 88 dp image (I-14), the app name, and
 * Prev / Next (40 dp circles, 48 dp targets; LoadAction → POST /api/playlist/prev|next, then re-render). A tap
 * elsewhere opens Now Playing. One engine round-trip per request; nothing runs between requests.
 */
class DeskDotTileService : TileService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    @Volatile private var frame: ByteArray? = null

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun <T> future(block: suspend () -> T): ListenableFuture<T> = CallbackToFutureAdapter.getFuture { c ->
        scope.launch {
            try {
                c.set(block())
            } catch (t: Throwable) {
                c.setException(t)
            }
        }
        "deskdot-tile"
    }

    override fun onTileRequest(requestParams: RequestBuilders.TileRequest): ListenableFuture<TileBuilders.Tile> = future {
        val dd = Dd.get(this)
        val sig = SuiteSignalSource.read(this, dd.prefs, SuiteSignals())
        val accent = if (sig.lowEnergy) 0xFFF2F3F5.toInt() else AccentThemes.of(sig.accent).accent.toArgb()
        val clicked = requestParams.currentState.lastClickableId
        val up = dd.engine.probe(1_500)
        var name = "Engine off"
        var ver = "off"
        if (up) {
            if (clicked == "prev" || clicked == "next") dd.engine.post("/api/playlist/$clicked")
            val st = dd.engine.refreshState()
            if (dd.meta.value == null) dd.loadMeta()
            name = dd.meta.value?.name(st?.currentApp)?.ifEmpty { null } ?: st?.currentApp ?: "DeskDot"
            if (dd.engine.pollFrame(2_000)) {
                frame = synchronized(dd.engine.frame) { dd.engine.frame.copyOf() }
                ver = "f" + frame.contentHashCode()
            }
        }
        TileBuilders.Tile.Builder()
            .setResourcesVersion(ver)
            .setFreshnessIntervalMillis(15 * 60_000L)
            .setTileTimeline(TimelineBuilders.Timeline.fromLayoutElement(layout(name, accent, up && ver != "off", sig.lowEnergy)))
            .build()
    }

    override fun onTileResourcesRequest(requestParams: RequestBuilders.ResourcesRequest): ListenableFuture<ResourceBuilders.Resources> = future {
        val b = ResourceBuilders.Resources.Builder().setVersion(requestParams.version)
        frame?.let { b.addIdToImageMapping(IMG_FRAME, rgb565(renderFrame(it), FRAME_PX)) }
        b.addIdToImageMapping(IMG_PREV, rgb565(renderIcon(prev = true), ICON_PX))
        b.addIdToImageMapping(IMG_NEXT, rgb565(renderIcon(prev = false), ICON_PX))
        b.build()
    }

    private fun layout(name: String, accent: Int, hasFrame: Boolean, le: Boolean): LayoutElementBuilders.LayoutElement {
        val open = ModifiersBuilders.Clickable.Builder()
            .setId("open")
            .setOnClick(
                ActionBuilders.LaunchAction.Builder().setAndroidActivity(
                    ActionBuilders.AndroidActivity.Builder().setPackageName(packageName).setClassName("com.deskdot.app.MainActivity").build(),
                ).build(),
            ).build()
        val col = LayoutElementBuilders.Column.Builder()
            .setHorizontalAlignment(LayoutElementBuilders.HORIZONTAL_ALIGN_CENTER)
            .addContent(text("DeskDot", 12f, accent, bold = true))
            .addContent(spacer(6f))
        if (hasFrame) {
            col.addContent(
                LayoutElementBuilders.Image.Builder().setResourceId(IMG_FRAME).setWidth(dp(88f)).setHeight(dp(88f)).build(),
            )
        } else {
            col.addContent(
                LayoutElementBuilders.Box.Builder().setWidth(dp(88f)).setHeight(dp(88f))
                    .setVerticalAlignment(LayoutElementBuilders.VERTICAL_ALIGN_CENTER)
                    .addContent(text(name, 12f, 0xFFB4B9C2.toInt())).build(),
            )
        }
        col.addContent(spacer(8f))
            .addContent(text(if (hasFrame) name else "Tap to start", 15f, 0xFFF2F3F5.toInt(), bold = true))
            .addContent(spacer(6f))
            .addContent(
                LayoutElementBuilders.Row.Builder()
                    .addContent(button("prev", IMG_PREV, le))
                    .addContent(LayoutElementBuilders.Spacer.Builder().setWidth(dp(20f)).build())
                    .addContent(button("next", IMG_NEXT, le))
                    .build(),
            )
        return LayoutElementBuilders.Box.Builder()
            .setWidth(expand()).setHeight(expand())
            .setModifiers(ModifiersBuilders.Modifiers.Builder().setClickable(open).build())
            .addContent(col.build())
            .build()
    }

    private fun button(id: String, img: String, le: Boolean): LayoutElementBuilders.LayoutElement {
        val bg = ModifiersBuilders.Background.Builder()
            .setColor(argb(if (le) 0xFF000000.toInt() else 0xFF1C1E22.toInt()))
            .setCorner(ModifiersBuilders.Corner.Builder().setRadius(dp(20f)).build())
            .build()
        val border = if (le) ModifiersBuilders.Border.Builder().setWidth(dp(1f)).setColor(argb(0xFF3A3E45.toInt())).build() else null
        val inner = LayoutElementBuilders.Box.Builder().setWidth(dp(40f)).setHeight(dp(40f))
            .setModifiers(ModifiersBuilders.Modifiers.Builder().setBackground(bg).apply { border?.let { setBorder(it) } }.build())
            .addContent(LayoutElementBuilders.Image.Builder().setResourceId(img).setWidth(dp(24f)).setHeight(dp(24f)).build())
            .build()
        return LayoutElementBuilders.Box.Builder().setWidth(dp(48f)).setHeight(dp(48f))
            .setModifiers(
                ModifiersBuilders.Modifiers.Builder()
                    .setClickable(ModifiersBuilders.Clickable.Builder().setId(id).setOnClick(ActionBuilders.LoadAction.Builder().build()).build())
                    .setSemantics(ModifiersBuilders.Semantics.Builder().setContentDescription(if (id == "prev") "Previous" else "Next").build())
                    .build(),
            )
            .addContent(inner)
            .build()
    }

    private fun text(s: String, size: Float, color: Int, bold: Boolean = false) = LayoutElementBuilders.Text.Builder()
        .setText(s)
        .setMaxLines(1)
        .setOverflow(LayoutElementBuilders.TEXT_OVERFLOW_ELLIPSIZE_END)
        .setFontStyle(
            LayoutElementBuilders.FontStyle.Builder().setSize(sp(size)).setColor(argb(color))
                .setWeight(if (bold) LayoutElementBuilders.FONT_WEIGHT_BOLD else LayoutElementBuilders.FONT_WEIGHT_NORMAL).build(),
        )
        .build()

    private fun spacer(h: Float) = LayoutElementBuilders.Spacer.Builder().setHeight(dp(h)).build()

    /** 32x32 RGB → 176x176 dots (pitch 5.5, r 2.4), unlit #141518, on black. */
    private fun renderFrame(rgb: ByteArray): Bitmap {
        val bmp = Bitmap.createBitmap(FRAME_PX, FRAME_PX, Bitmap.Config.RGB_565)
        val c = Canvas(bmp)
        val p = Paint(Paint.ANTI_ALIAS_FLAG)
        for (y in 0 until 32) for (x in 0 until 32) {
            val i = (y * 32 + x) * 3
            val r = rgb[i].toInt() and 0xFF
            val g = rgb[i + 1].toInt() and 0xFF
            val b = rgb[i + 2].toInt() and 0xFF
            p.color = if (r + g + b < 24) 0xFF141518.toInt() else (0xFF shl 24) or (r shl 16) or (g shl 8) or b
            c.drawCircle(5.5f * x + 2.75f, 5.5f * y + 2.75f, 2.4f, p)
        }
        return bmp
    }

    /** skip_previous / skip_next (filled triangle + bar), on the button colour. */
    private fun renderIcon(prev: Boolean): Bitmap {
        val bmp = Bitmap.createBitmap(ICON_PX, ICON_PX, Bitmap.Config.RGB_565)
        val c = Canvas(bmp)
        c.drawColor(0xFF1C1E22.toInt())
        val k = ICON_PX / 24f
        val p = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFFF2F3F5.toInt() }
        val tri = Path().apply {
            if (prev) { moveTo(18f * k, 6f * k); lineTo(18f * k, 18f * k); lineTo(9f * k, 12f * k) } else { moveTo(6f * k, 6f * k); lineTo(6f * k, 18f * k); lineTo(15f * k, 12f * k) }
            close()
        }
        c.drawPath(tri, p)
        val x = if (prev) 7f * k else 17f * k
        c.drawRoundRect(x - k, 6f * k, x + k, 18f * k, k, k, p)
        return bmp
    }

    private fun rgb565(bmp: Bitmap, px: Int): ResourceBuilders.ImageResource {
        val buf = ByteBuffer.allocate(bmp.byteCount)
        bmp.copyPixelsToBuffer(buf)
        return ResourceBuilders.ImageResource.Builder().setInlineResource(
            ResourceBuilders.InlineImageResource.Builder()
                .setData(buf.array()).setWidthPx(px).setHeightPx(px)
                .setFormat(ResourceBuilders.IMAGE_FORMAT_RGB_565).build(),
        ).build()
    }

    companion object {
        private const val IMG_FRAME = "frame"
        private const val IMG_PREV = "prev"
        private const val IMG_NEXT = "next"
        private const val FRAME_PX = 176
        private const val ICON_PX = 48

        /** Ask the system to refresh the Tile (after the playlist changes from the app). */
        fun refresh(ctx: android.content.Context) = runCatching {
            getUpdater(ctx).requestUpdate(DeskDotTileService::class.java)
        }

    }
}
