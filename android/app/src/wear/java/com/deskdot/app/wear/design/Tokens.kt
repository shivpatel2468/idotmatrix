package com.deskdot.app.wear.design

import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color

/** DESIGN_SPEC.md §1.1 neutral palette. */
object Neutral {
    val bg = Color(0xFF000000)
    val surface0 = Color(0xFF0B0C0E)
    val surface1 = Color(0xFF141518)
    val surface2 = Color(0xFF1C1E22)
    val surface3 = Color(0xFF26292E)
    val outline = Color(0xFF3A3E45)
    val outlineVariant = Color(0xFF2A2D33)
    val onSurface = Color(0xFFF2F3F5)
    val onSurfaceVariant = Color(0xFFB4B9C2)
    val onSurfaceMuted = Color(0xFF7C828C)

    /** §1.12: overlay scrim #000000 @ 94% (0xF0). */
    val scrim94 = Color(0xF0000000)

    /** §4.3 unselected page dot: #FFFFFF @ 30%. */
    val white30 = Color(0x4DFFFFFF)
}

/** §1.4 semantic colours. */
object Semantic {
    val ok = Color(0xFF5BD68A)
    val warn = Color(0xFFFFC24A)
    val error = Color(0xFFFF5A5F)
    val info = Color(0xFF6CC4FF)
}

/** §1.3 accent themes. Ember is the default. */
enum class AccentId(val title: String) { Ember("Ember"), Glacier("Glacier"), Moss("Moss"), Graphite("Graphite") }

@Immutable
data class AccentRoles(
    val id: AccentId,
    val accent: Color,
    val accentLight: Color,
    val accentDeep: Color,
    val accentLine: Color,
    val onAccent: Color,
    val ambAccent: Color,
)

object AccentThemes {
    private val ember = AccentRoles(
        AccentId.Ember, Color(0xFFFF4818), Color(0xFFFF7A4D), Color(0xFF3A1208),
        Color(0xFF7A2A12), Color(0xFF150502), Color(0xFFC2401A),
    )
    private val glacier = AccentRoles(
        AccentId.Glacier, Color(0xFF6CC4FF), Color(0xFFA8DDFF), Color(0xFF0B2638),
        Color(0xFF1F5677), Color(0xFF021522), Color(0xFF5E9CC8),
    )
    private val moss = AccentRoles(
        AccentId.Moss, Color(0xFF8FD16A), Color(0xFFBDE8A1), Color(0xFF142A0C),
        Color(0xFF3F6B2A), Color(0xFF071203), Color(0xFF78A85E),
    )
    private val graphite = AccentRoles(
        AccentId.Graphite, Color(0xFFC9CED6), Color(0xFFE8EBEF), Color(0xFF24272C),
        Color(0xFF4A4F57), Color(0xFF111316), Color(0xFFA9AFB8),
    )

    fun of(id: AccentId): AccentRoles = when (id) {
        AccentId.Ember -> ember
        AccentId.Glacier -> glacier
        AccentId.Moss -> moss
        AccentId.Graphite -> graphite
    }
}

/** §1.7 round-screen geometry, in px (416x416, density 320 => 1 dp = 2 px). */
object Geometry {
    const val SCREEN = 416
    const val C = 208f

    /** §4.2.8 readable band. */
    const val READ_TOP = 92
    const val READ_BOTTOM = 340

    /** Row width available at vertical offset d from centre, per §1.7. */
    fun rowWidth(d: Float): Float {
        val inner = 208f * 208f - d * d
        val s = if (inner > 0f) kotlin.math.sqrt(inner) else 0f
        return 2f * s - 24f
    }
}
