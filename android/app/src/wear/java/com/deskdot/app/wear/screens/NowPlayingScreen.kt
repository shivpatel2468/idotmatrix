package com.deskdot.app.wear.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.foundation.clickable
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.TimeText
import com.deskdot.app.wear.net.EngineClient
import com.deskdot.app.wear.ui.DotGridPreview
import kotlinx.coroutines.launch

/**
 * DESIGN_SPEC §5.3 Now Playing (page 0 of the home pager). A fixed layout (no edge-fade mask is applied, per
 * the spec's own "Now Playing is a fixed layout" rule). Geometry is simplified from the spec's exact px
 * placements (112x112 grid + ring/buttons at hard-coded centres) to a centred column that keeps the same
 * element order and relative spacing; see the final report for this deviation.
 */
@Composable
fun NowPlayingScreen(engine: EngineClient, nav: NavHostController) {
    val scope = rememberCoroutineScope()
    val frame by engine.frame.collectAsStateWithLifecycle()
    val state by engine.state.collectAsStateWithLifecycle()

    DisposableEffect(Unit) {
        engine.connect(scope)
        onDispose { engine.disconnect() }
    }

    val activeApp = state?.optString("active", "-") ?: "-"
    val playlist = state?.optJSONObject("playlist")
    val playing = playlist?.optBoolean("playing", false) ?: false

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Box(
                Modifier.clickable { scope.launch { engine.post("/api/playlist/${if (playing) "stop" else "play"}") } },
            ) {
                DotGridPreview(frame = frame, cellSize = 6.dp)
            }
        }
        Box(Modifier.fillMaxSize().padding(bottom = 48.dp), contentAlignment = Alignment.BottomCenter) {
            Text(text = activeApp)
        }
        // Prev / Next: left and right of the preview.
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterStart) {
            IconDot("‹") { scope.launch { engine.post("/api/playlist/prev") } }
        }
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterEnd) {
            IconDot("›") { scope.launch { engine.post("/api/playlist/next") } }
        }
        // Now Playing is a fixed layout (no edge-fade mask), but TimeText is still shown, per §5.3's own row.
        TimeText()
    }
}

@Composable
private fun IconDot(glyph: String, onClick: () -> Unit) {
    Box(
        Modifier
            .padding(horizontal = 18.dp)
            .clip(androidx.compose.foundation.shape.CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = glyph)
    }
}
