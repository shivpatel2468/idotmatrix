package com.deskdot.app.wear.ui

import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.graphicsLayer

/**
 * DESIGN_SPEC §4.2.8 (rev 1.2), owner override: no shadow, halo, scrim or black band behind the top-centre
 * clock (TimeText) or the page indicator or any other text. Scrolling content fades **itself** out with an
 * alpha mask instead, via an offscreen `graphicsLayer` + `BlendMode.DstIn` gradient.
 *
 * Band table (px, on a 416x416 round screen):
 *   0-36    alpha 0      (TimeText ink ~20-46)
 *   36-92   0 -> 1 ramp
 *   92-340  alpha 1      (fully readable band)
 *   340-396 1 -> 0 ramp
 *   396-416 alpha 0      (page-indicator dots ~396-408)
 *
 * Apply this to the **scrolling container only** (a ScalingLazyColumn, or the list + lens Box). TimeText, the
 * page indicator and any fixed overlay are drawn as siblings AFTER this modifier's content and are never masked.
 * Fixed-layout screens (QR pages, Now Playing, Gamepad, the brightness gauge) do not use this modifier at all.
 */
fun Modifier.edgeFadeMask(): Modifier = composed {
    val brush = remember {
        Brush.verticalGradient(
            0f to Color.Transparent,
            (36f / 416f) to Color.Transparent,
            (92f / 416f) to Color.Black,
            (340f / 416f) to Color.Black,
            (396f / 416f) to Color.Transparent,
            1f to Color.Transparent,
        )
    }
    this
        .graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }
        .drawWithContent {
            drawContent()
            drawRect(brush = brush, blendMode = BlendMode.DstIn)
        }
}
