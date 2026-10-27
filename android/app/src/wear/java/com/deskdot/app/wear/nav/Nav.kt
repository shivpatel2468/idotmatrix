package com.deskdot.app.wear.nav

import android.net.Uri
import androidx.compose.runtime.Immutable
import androidx.navigation.NavHostController

/** Route names (androidx.wear.compose.navigation; every destination is swipe-dismissable). */
object Route {
    const val HOME = "home"
    const val WELCOME = "onboard/welcome"
    const val PERMS = "onboard/perms"
    const val SCAN = "onboard/scan"
    const val CONNECT = "onboard/connect?addr={addr}&name={name}"
    const val FULL = "now/full"
    const val APP_LIST = "apps/list?cat={cat}"
    const val SEARCH = "apps/search?q={q}"
    const val APP = "app/{id}"
    const val GAME = "game/{id}"
    const val LOBBY = "lobby"
    const val GAMEPAD = "gamepad/{id}"
    const val CASINO = "casino"
    const val TV = "tv"
    const val PL_ITEM = "playlist/item/{id}"
    const val PL_NEW = "playlist/new"
    const val PANEL = "more/panel"
    const val DISPLAY = "more/display"
    const val ENGINE = "more/engine"
    const val STUDIO = "more/studio"
    const val SETTINGS = "more/settings"
    const val ACCENT = "settings/accent"
    const val LOW_ENERGY = "settings/le"
    const val CHOICE = "pick/choice"
    const val NUMBER = "pick/number"
    const val COLOR = "pick/color"
}

fun NavHostController.connect(addr: String, name: String) =
    navigate("onboard/connect?addr=${Uri.encode(addr)}&name=${Uri.encode(name)}")

fun NavHostController.appList(cat: String) = navigate("apps/list?cat=${Uri.encode(cat)}")
fun NavHostController.search(q: String) = navigate("apps/search?q=${Uri.encode(q)}")
fun NavHostController.app(id: String) = navigate("app/${Uri.encode(id)}")
fun NavHostController.game(id: String) = navigate("game/${Uri.encode(id)}")
fun NavHostController.gamepad(id: String) = navigate("gamepad/${Uri.encode(id)}")
fun NavHostController.plItem(id: String) = navigate("playlist/item/${Uri.encode(id)}")

/** Leaves onboarding for the main pager, clearing the onboarding back stack. */
fun NavHostController.home() = navigate(Route.HOME) { popUpTo(0) { inclusive = true } }

/** Back to the panel-scan step from anywhere (Forget / Change panel / "No" on the HI test). */
fun NavHostController.rescan() = navigate(Route.SCAN) { launchSingleTop = true }

// ---------------------------------------------------------------------------------- picker requests

@Immutable
data class ChoiceReq(
    val title: String,
    val options: List<Pair<String, String>>, // value to label
    val selected: String?,
    val onPick: (String) -> Unit,
)

@Immutable
data class NumberReq(
    val title: String,
    val value: Double,
    val min: Double,
    val max: Double,
    val step: (Double, Int) -> Double,
    val format: (Double) -> String,
    val onChange: (Double) -> Unit,
)

@Immutable
data class ColorReq(val title: String, val palette: List<Pair<String, String>>, val selected: String?, val onPick: (String) -> Unit)

/**
 * The generic pickers take their request from here (one at a time, set right before navigating), so screens do
 * not need to serialise lambdas into routes.
 */
object Pick {
    var choice: ChoiceReq? = null
    var number: NumberReq? = null
    var color: ColorReq? = null

    fun choice(nav: NavHostController, r: ChoiceReq) { choice = r; nav.navigate(Route.CHOICE) }
    fun number(nav: NavHostController, r: NumberReq) { number = r; nav.navigate(Route.NUMBER) }
    fun color(nav: NavHostController, r: ColorReq) { color = r; nav.navigate(Route.COLOR) }

    /** Linear steps clamped to [min, max]. */
    fun linear(step: Double, min: Double, max: Double): (Double, Int) -> Double = { v, d -> (v + d * step).coerceIn(min, max) }
}
