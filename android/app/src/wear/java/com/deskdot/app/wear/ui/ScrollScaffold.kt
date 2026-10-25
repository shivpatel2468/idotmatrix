package com.deskdot.app.wear.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.ScalingLazyColumn
import androidx.wear.compose.foundation.lazy.ScalingLazyListAnchorType
import androidx.wear.compose.foundation.lazy.ScalingLazyListScope
import androidx.wear.compose.foundation.lazy.ScalingLazyListState
import androidx.wear.compose.foundation.lazy.rememberScalingLazyListState
import androidx.wear.compose.material.TimeText

/**
 * DESIGN_SPEC §4.2.8 rule R1 (rev 1.2): every scrolling screen uses these exact ScalingLazyColumn parameters so
 * content never looks faded at rest (the first item's top sits at y >= 92 px, the last item's bottom at
 * y <= 340 px) — these replace the plain §4.2 defaults. `autoCentering = null` is required: with it on, the
 * first/last items would scroll past the padding to the screen centre.
 *
 * TimeText is drawn as a sibling AFTER the (masked) list, per the owner override: nothing sits behind it.
 */
@Composable
fun rememberEdgeSafeListState(initialCenterItemIndex: Int = 0): ScalingLazyListState =
    rememberScalingLazyListState(initialCenterItemIndex = initialCenterItemIndex)

val EdgeSafeContentPadding = PaddingValues(start = 10.dp, end = 10.dp, top = 46.dp, bottom = 38.dp)

@Composable
fun ScrollScaffold(
    state: ScalingLazyListState = rememberEdgeSafeListState(),
    showTimeText: Boolean = true,
    content: ScalingLazyListScope.() -> Unit,
) {
    Box(Modifier.fillMaxSize()) {
        ScalingLazyColumn(
            modifier = Modifier.fillMaxSize().edgeFadeMask(),
            state = state,
            autoCentering = null, // rev 1.2 rule R1 - see kdoc above
            contentPadding = EdgeSafeContentPadding,
            anchorType = ScalingLazyListAnchorType.ItemCenter,
            content = content,
        )
        if (showTimeText) {
            // Drawn after (so visually on top of) the masked list; nothing is drawn behind it (owner override).
            TimeText()
        }
    }
}
