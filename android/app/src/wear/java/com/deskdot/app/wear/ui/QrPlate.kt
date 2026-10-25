package com.deskdot.app.wear.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel

/**
 * DESIGN_SPEC §5.5.3: a solid white plate with black, pixel-aligned QR modules, no anti-aliasing, ECC level M.
 * Used for the games lobby join QR, the TV link QR and the studio-sharing QR (§5.10).
 */
@Composable
fun QrPlate(content: String, plateSizeDp: Int = 130, modifier: Modifier = Modifier) {
    val matrix = remember(content) {
        runCatching {
            QRCodeWriter().encode(
                content,
                BarcodeFormat.QR_CODE,
                0,
                0,
                mapOf(EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M, EncodeHintType.MARGIN to 0),
            )
        }.getOrNull()
    }
    Canvas(modifier = modifier.size(plateSizeDp.dp)) {
        drawRect(color = Color.White, size = Size(size.width, size.height))
        val m = matrix ?: return@Canvas
        val modulePx = (size.width / m.width.toFloat())
        for (y in 0 until m.height) {
            for (x in 0 until m.width) {
                if (m.get(x, y)) {
                    drawRect(
                        color = Color.Black,
                        topLeft = Offset(x * modulePx, y * modulePx),
                        size = Size(modulePx, modulePx),
                    )
                }
            }
        }
    }
}
