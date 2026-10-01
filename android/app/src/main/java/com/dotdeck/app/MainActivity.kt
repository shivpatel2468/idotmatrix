package com.dotdeck.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts

/**
 * The studio, full screen. Asks for Bluetooth (and notification) permission, starts [EngineService], offers the
 * battery-optimisation exemption that keeps Android from killing it, then shows http://127.0.0.1:8765 — the same
 * studio as on the laptop, served by the engine running on this phone.
 */
class MainActivity : ComponentActivity() {
    private lateinit var web: WebView
    private lateinit var status: TextView
    private val main = Handler(Looper.getMainLooper())
    private var loaded = false

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

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.BLACK
        web = WebView(this).apply {
            setBackgroundColor(Color.BLACK)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            webViewClient = object : WebViewClient() {
                override fun onReceivedError(v: WebView, req: WebResourceRequest, err: WebResourceError) {
                    if (req.isForMainFrame) retrySoon() // the engine is still starting
                }

                override fun onPageFinished(v: WebView, url: String) {
                    if (url.startsWith(STUDIO)) {
                        loaded = true
                        status.visibility = View.GONE
                    }
                }
            }
        }
        status = TextView(this).apply {
            setTextColor(Color.rgb(249, 74, 24))
            textSize = 16f
            setBackgroundColor(Color.BLACK)
            gravity = android.view.Gravity.CENTER
            text = getString(R.string.starting)
        }
        setContentView(FrameLayout(this).apply { addView(web); addView(status) })
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else moveTaskToBack(true) // keep running, just go home
            }
        })
        val missing = permissions.filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) onPermissions() else ask.launch(missing.toTypedArray())
    }

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
        web.loadUrl(STUDIO)
    }

    private fun retrySoon() {
        loaded = false
        status.visibility = View.VISIBLE
        status.text = getString(R.string.starting)
        main.postDelayed({ if (!loaded) load() }, 1500)
    }

    override fun onDestroy() {
        main.removeCallbacksAndMessages(null)
        web.destroy()
        super.onDestroy()
    }

    companion object {
        const val STUDIO = "http://127.0.0.1:${EngineService.PORT}/"
    }
}
