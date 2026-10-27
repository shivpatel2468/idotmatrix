package com.deskdot.app.wear.complication

import android.app.PendingIntent
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon
import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.MonochromaticImage
import androidx.wear.watchface.complications.data.MonochromaticImageComplicationData
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.data.ShortTextComplicationData
import androidx.wear.watchface.complications.data.SmallImage
import androidx.wear.watchface.complications.data.SmallImageComplicationData
import androidx.wear.watchface.complications.data.SmallImageType
import androidx.wear.watchface.complications.datasource.ComplicationDataSourceUpdateRequester
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import androidx.wear.watchface.complications.datasource.SuspendingComplicationDataSourceService
import com.deskdot.app.MainActivity
import com.deskdot.app.R
import com.deskdot.app.wear.Dd
import com.deskdot.app.wear.net.DeviceInfo

/**
 * Watch-face complication: the panel status. SHORT_TEXT reads "✓ Panel" / "! Panel" / "× Panel" (glyph +
 * word, never colour alone) or "Off" when the engine isn't running; the image types show the DeskDot mark.
 * Push-only (UPDATE_PERIOD 0): one engine call per request, [ComplicationPush] asks for a refresh.
 */
class DeskDotComplicationService : SuspendingComplicationDataSourceService() {
    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData? {
        val dd = Dd.get(this)
        val st = dd.engine.get("/api/state", 1_500)
        val dev = st?.let { DeviceInfo.parse(it.optJSONObject("device")) }
        return build(request.complicationType, dev, st != null)
    }

    override fun getPreviewData(type: ComplicationType): ComplicationData? =
        build(type, DeviceInfo(status = "connected", name = "IDM-3F21A0"), true)

    private fun build(type: ComplicationType, dev: DeviceInfo?, up: Boolean): ComplicationData? {
        val (glyph, word) = when {
            !up -> "" to "Off"
            dev?.connected == true -> "✓" to "connected"
            dev?.connecting == true -> "!" to "connecting"
            else -> "×" to "offline"
        }
        val short = if (!up) "Off" else "$glyph Panel"
        val desc = PlainComplicationText.Builder(if (!up) "DeskDot engine off" else "DeskDot panel $word").build()
        val tap = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val icon = Icon.createWithResource(this, R.drawable.ic_stat_deskdot)
        return when (type) {
            ComplicationType.SHORT_TEXT -> ShortTextComplicationData.Builder(PlainComplicationText.Builder(short).build(), desc)
                .setMonochromaticImage(MonochromaticImage.Builder(icon).build())
                .setTapAction(tap)
                .build()
            ComplicationType.MONOCHROMATIC_IMAGE -> MonochromaticImageComplicationData.Builder(MonochromaticImage.Builder(icon).build(), desc)
                .setTapAction(tap).build()
            ComplicationType.SMALL_IMAGE -> SmallImageComplicationData.Builder(SmallImage.Builder(icon, SmallImageType.ICON).build(), desc)
                .setTapAction(tap).build()
            else -> null
        }
    }
}

/** Asks every watch face showing the complication to re-request it (called when the panel status changes). */
object ComplicationPush {
    fun request(ctx: Context) = runCatching {
        ComplicationDataSourceUpdateRequester.create(ctx, ComponentName(ctx, DeskDotComplicationService::class.java)).requestUpdateAll()
    }
}
