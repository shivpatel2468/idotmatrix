package com.deskdot.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.ComponentName
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.Display
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import org.json.JSONArray
import org.json.JSONObject

/**
 * The studio, full screen. Asks for Bluetooth (and notification) permission, starts [EngineService], offers the
 * battery-optimisation exemption that keeps Android from killing it, then shows http://127.0.0.1:8765 — the same
 * studio as on the laptop, served by the engine running on this phone.
 *
 * Phone polish (android/README.md → "The app shell"):
 *  - the highest refresh rate the screen offers (120 Hz on most recent phones) at the current resolution;
 *  - `window.DeskDotAndroid` for the studio: system bar colours + icon contrast that follow the studio theme
 *    (remembered, so the next cold start opens in the right colours with no black flash), and the launcher icon
 *    choice (one <activity-alias> per icon in the manifest; exactly one enabled).
 */
class MainActivity : ComponentActivity() {
    private lateinit var root: FrameLayout
    private lateinit var web: WebView
    private lateinit var status: TextView
    private lateinit var prefs: SharedPreferences
    private val main = Handler(Looper.getMainLooper())
    private var loaded = false
    private var failed = false // the last load hit an error page (the engine was still starting)

    private val permissions: Array<String>
        get() = buildList {
            if (Build.VERSION.SDK_INT >= 31) {
                add(Manifest.permission.BLUETOOTH_SCAN)
                add(Manifest.permission.BLUETOOTH_CONNECT)
            } else {
                add(Manifest.permission.ACCESS_FINE_LOCATION)
            }
            if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
        }.toTypedArray()

    private val ask = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { onPermissions() }

    @SuppressLint("SetJavaScriptEnabled", "JavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE)
        // GPU compositing for the whole window (the default since API 14 — stated, so no theme or OEM overlay drops it)
        window.setFlags(WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED, WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED)
        requestHighRefreshRate()
        val bars = Bars.load(prefs, isNight())
        web = WebView(this).apply {
            setBackgroundColor(bars.page)
            // The WebView keeps the default layer type on purpose: it already draws on the GPU through the window's
            // hardware renderer. LAYER_TYPE_HARDWARE would add an off-screen copy of the whole page every frame
            // (more GPU memory, a full-screen blit per frame) and Chromium advises against it.
            overScrollMode = View.OVER_SCROLL_NEVER // the page handles its own overscroll; no Android glow/stretch on top
            isVerticalScrollBarEnabled = false
            isHorizontalScrollBarEnabled = false
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.offscreenPreRaster = true // raster tiles just outside the viewport too: no checkerboard on fast flings
            if (Build.VERSION.SDK_INT >= 26) setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, true)
            addJavascriptInterface(Bridge(), "DeskDotAndroid")
            webViewClient = object : WebViewClient() {
                override fun onReceivedError(v: WebView, req: WebResourceRequest, err: WebResourceError) {
                    if (req.isForMainFrame) {
                        failed = true // the error page's onPageFinished must not count as loaded
                        retrySoon() // the engine is still starting
                    }
                }

                override fun onPageFinished(v: WebView, url: String) {
                    if (url.startsWith(STUDIO) && !failed) {
                        loaded = true
                        status.visibility = View.GONE
                    }
                }

                // only the studio (this phone's engine) opens in here — and only it sees DeskDotAndroid; any other
                // link opens in the browser
                override fun shouldOverrideUrlLoading(v: WebView, req: WebResourceRequest): Boolean {
                    val host = req.url.host ?: return false
                    if (host == "127.0.0.1" || host == "localhost") return false
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, req.url))
                    } catch (e: Exception) {
                        // no browser: stay put
                    }
                    return true
                }
            }
        }
        status = TextView(this).apply {
            setTextColor(Color.rgb(249, 74, 24))
            textSize = 16f
            gravity = android.view.Gravity.CENTER
            text = getString(R.string.starting)
        }
        root = FrameLayout(this).apply { addView(web); addView(status) }
        setContentView(root)
        applyBars(bars)
        if (Build.VERSION.SDK_INT >= 35) {
            // Android 15 always draws apps edge to edge: keep the studio clear of the bars; the window background
            // (the theme's page colour, applyBars) shows behind them
            ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
                val b = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
                v.setPadding(b.left, b.top, b.right, b.bottom)
                WindowInsetsCompat.CONSUMED
            }
        }
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else moveTaskToBack(true) // keep running, just go home
            }
        })
        val missing = permissions.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) onPermissions() else ask.launch(missing.toTypedArray())
    }

    override fun onResume() {
        super.onResume()
        requestHighRefreshRate() // some OEM skins reset the window's mode when the app comes back
    }

    private fun isNight() =
        (resources.configuration.uiMode and Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES

    // ------------------------------------------------------------------------------------------- refresh rate

    @Suppress("DEPRECATION")
    private fun screen(): Display? = if (Build.VERSION.SDK_INT >= 30) display else windowManager.defaultDisplay

    /** Ask for the fastest mode at the current resolution (60 → 90/120/144 Hz); the system may still lower it. */
    private fun requestHighRefreshRate() {
        val d = screen() ?: return
        val cur = d.mode
        val best = d.supportedModes
            .filter { it.physicalWidth == cur.physicalWidth && it.physicalHeight == cur.physicalHeight }
            .maxByOrNull { it.refreshRate } ?: return
        val lp = window.attributes
        if (lp.preferredDisplayModeId == best.modeId) return
        lp.preferredDisplayModeId = best.modeId
        lp.preferredRefreshRate = best.refreshRate
        window.attributes = lp
    }

    // ------------------------------------------------------------------------------------------- system bars

    /** The bar colours of one studio theme. `lightIcons` = white status / navigation icons (a dark theme). */
    private data class Bars(val status: Int, val nav: Int, val page: Int, val lightIcons: Boolean) {
        fun save(p: SharedPreferences) =
            p.edit().putInt("bar_status", status).putInt("bar_nav", nav).putInt("bar_page", page)
                .putBoolean("bar_light_icons", lightIcons).apply()

        companion object {
            // the studio's own colours (web/src/index.css): header chassis-1, tab bar --m-glass, page chassis-0
            val DARK = Bars(Color.parseColor("#0F0F13"), Color.parseColor("#0E0E12"), Color.parseColor("#08080A"), true)
            val LIGHT = Bars(Color.parseColor("#FBF9F5"), Color.parseColor("#FBF9F5"), Color.parseColor("#F4F0E8"), false)

            fun load(p: SharedPreferences, night: Boolean): Bars {
                if (!p.contains("bar_page")) return if (night) DARK else LIGHT // first start: the studio's "Auto"
                return Bars(p.getInt("bar_status", 0), p.getInt("bar_nav", 0), p.getInt("bar_page", 0), p.getBoolean("bar_light_icons", true))
            }
        }
    }

    private fun applyBars(b: Bars) {
        window.setBackgroundDrawable(ColorDrawable(b.page))
        root.setBackgroundColor(b.page)
        web.setBackgroundColor(b.page)
        status.setBackgroundColor(b.page)
        barColours(b)
        if (Build.VERSION.SDK_INT >= 29) window.isNavigationBarContrastEnforced = false // no grey scrim on 3-button nav
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = !b.lightIcons
            isAppearanceLightNavigationBars = !b.lightIcons
        }
    }

    @Suppress("DEPRECATION") // ignored on Android 15+ (edge to edge): the window background shows behind the bars there
    private fun barColours(b: Bars) {
        window.statusBarColor = b.status
        window.navigationBarColor = b.nav
    }

    // ------------------------------------------------------------------------------------------- launcher icon

    private fun alias(id: String) = ComponentName(packageName, "$packageName.Launcher" + id.replaceFirstChar { it.uppercase() })

    private fun currentIcon(): String = ICONS.firstOrNull {
        when (packageManager.getComponentEnabledSetting(alias(it))) {
            PackageManager.COMPONENT_ENABLED_STATE_ENABLED -> true
            PackageManager.COMPONENT_ENABLED_STATE_DEFAULT -> it == DEFAULT_ICON // the manifest enables only the default
            else -> false
        }
    } ?: DEFAULT_ICON

    /** Enable the chosen alias first, then disable the rest — there is never a moment with no launcher entry. */
    private fun switchIcon(id: String) {
        val pm = packageManager
        pm.setComponentEnabledSetting(alias(id), PackageManager.COMPONENT_ENABLED_STATE_ENABLED, PackageManager.DONT_KILL_APP)
        for (other in ICONS) {
            if (other != id) {
                pm.setComponentEnabledSetting(alias(other), PackageManager.COMPONENT_ENABLED_STATE_DISABLED, PackageManager.DONT_KILL_APP)
            }
        }
    }

    // ------------------------------------------------------------------------------------------- the JS bridge

    /** `window.DeskDotAndroid` (web/src/lib/android.ts). Called on a binder thread: UI work is posted to the main one. */
    private inner class Bridge {
        @JavascriptInterface
        fun version(): Int = 1

        /** System bar colours (#rrggbb) for the studio theme on screen; `lightIcons` = white bar icons. */
        @JavascriptInterface
        fun setBars(statusHex: String, navHex: String, pageHex: String, lightIcons: Boolean) {
            val b = try {
                Bars(Color.parseColor(statusHex), Color.parseColor(navHex), Color.parseColor(pageHex), lightIcons)
            } catch (e: IllegalArgumentException) {
                return
            }
            main.post {
                applyBars(b)
                b.save(prefs)
            }
        }

        @JavascriptInterface
        fun icons(): String = JSONArray(ICONS).toString()

        @JavascriptInterface
        fun getIcon(): String = currentIcon()

        /** Switch the launcher icon. The launcher redraws within a few seconds; some launchers drop home-screen shortcuts. */
        @JavascriptInterface
        fun setIcon(id: String): Boolean {
            if (id !in ICONS) return false
            main.post { switchIcon(id) }
            return true
        }

        /** The screen's refresh rate now and the best it offers, e.g. {"hz":120,"max":120,"modes":[60,120]}. */
        @JavascriptInterface
        fun display(): String {
            val d = screen() ?: return "{}"
            val cur = d.mode
            val modes = d.supportedModes
                .filter { it.physicalWidth == cur.physicalWidth && it.physicalHeight == cur.physicalHeight }
                .map { Math.round(it.refreshRate) }.distinct().sorted()
            return JSONObject()
                .put("hz", Math.round(d.refreshRate))
                .put("max", modes.maxOrNull() ?: Math.round(d.refreshRate))
                .put("modes", JSONArray(modes))
                .toString()
        }
    }

    // ------------------------------------------------------------------------------------------- startup

    private fun onPermissions() {
        val bt = if (Build.VERSION.SDK_INT >= 31) Manifest.permission.BLUETOOTH_CONNECT else Manifest.permission.ACCESS_FINE_LOCATION
        if (checkSelfPermission(bt) != PackageManager.PERMISSION_GRANTED) {
            status.text = getString(R.string.need_bluetooth)
            status.setOnClickListener {
                startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
            }
            return
        }
        EngineService.start(this)
        askBatteryExemption()
        load()
    }

    @SuppressLint("BatteryLife") // sideloaded always-on host: exactly the case the exemption exists for
    private fun askBatteryExemption() {
        val pm = getSystemService(PowerManager::class.java)
        if (!pm.isIgnoringBatteryOptimizations(packageName)) {
            try {
                startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
            } catch (e: Exception) {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            }
        }
    }

    private fun load() {
        failed = false
        dropStaleCache()
        web.loadUrl(STUDIO)
    }

    /**
     * The studio files come out of the APK with one fixed date, so after an app update the page can look unchanged
     * to the WebView's cache (same date, same size) and an old studio would load. Clear the cache once per install.
     */
    private fun dropStaleCache() {
        val stamp = packageManager.getPackageInfo(packageName, 0).lastUpdateTime
        val prefs = getSharedPreferences("deskdot", MODE_PRIVATE)
        if (prefs.getLong("cache_stamp", 0L) != stamp) {
            web.clearCache(true)
            prefs.edit().putLong("cache_stamp", stamp).apply()
        }
    }

    private fun retrySoon() {
        loaded = false
        status.visibility = View.VISIBLE
        status.text = getString(R.string.starting)
        main.postDelayed({ if (!loaded || failed) load() }, 1500)
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        web.removeJavascriptInterface("DeskDotAndroid")
        web.destroy()
        super.onDestroy()
    }

    companion object {
        const val STUDIO = "http://127.0.0.1:${EngineService.PORT}/"
        private const val PREFS = "deskdot.ui"

        /** Launcher icons: one <activity-alias android:name=".Launcher<Id>"> each (android/tools/gen_icons.py draws them). */
        val ICONS = listOf("classic", "monogram", "ink", "sunset", "porcelain", "chip", "heart")

        /** The alias enabled in the manifest (android:enabled="true"); change both together. */
        const val DEFAULT_ICON = "classic"
    }
}
