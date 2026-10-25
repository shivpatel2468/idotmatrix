package com.deskdot.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts

/**
 * Wear launcher: a minimal, round-safe placeholder screen (black background, a status line, a button that opens
 * the studio). This is NOT the watch UI — the owner's round remote/studio screen is being designed separately
 * (see docs/adr/0012-wear-armv7-host.md) and will replace this activity. Until then this keeps the APK usable and
 * testable, and — per the memory budget on a 1 GB watch — it never inflates a WebView until the button is tapped.
 *
 * Shares [EngineService], [BleBridge] and the Python engine unchanged with the phone's MainActivity; only this
 * activity differs between the `mobile` and `wear` flavors (see android/app/build.gradle.kts).
 */
class MainActivity : ComponentActivity() {
    private lateinit var root: FrameLayout
    private lateinit var status: TextView
    private lateinit var openButton: Button
    private var web: WebView? = null

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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = Color.BLACK

        // A round-safe inset: content stays well inside the circle without pulling in the Wear UI library.
        val inset = (resources.displayMetrics.widthPixels * 0.22f).toInt()
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(inset, inset, inset, inset)
        }
        status = TextView(this).apply {
            setTextColor(Color.rgb(249, 74, 24))
            textSize = 13f
            gravity = Gravity.CENTER
            text = getString(R.string.starting)
        }
        openButton = Button(this).apply {
            text = getString(R.string.open_studio)
            isEnabled = false
            visibility = View.GONE
            setOnClickListener { showStudio() }
        }
        column.addView(status, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        column.addView(
            openButton,
            LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = 16 },
        )
        root = FrameLayout(this).apply {
            setBackgroundColor(Color.BLACK)
            addView(column, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        }
        setContentView(root)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                val w = web
                when {
                    w != null && w.canGoBack() -> w.goBack()
                    w != null -> hideStudio()
                    else -> moveTaskToBack(true) // keep the engine running, just go home
                }
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
        status.text = getString(R.string.note_running)
        openButton.isEnabled = true
        openButton.visibility = View.VISIBLE
    }

    /** Only now — on the user's tap — does the (heavy, ~tens of MB) WebView engine get touched. */
    @SuppressLint("SetJavaScriptEnabled")
    private fun showStudio() {
        if (web == null) {
            web = WebView(this).apply {
                setBackgroundColor(Color.BLACK)
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.mediaPlaybackRequiresUserGesture = false
                webViewClient = object : WebViewClient() {
                    override fun onReceivedError(v: WebView, req: WebResourceRequest, err: WebResourceError) {
                        if (req.isForMainFrame) v.postDelayed({ v.loadUrl(STUDIO) }, 1500) // engine still starting
                    }
                }
                loadUrl(STUDIO)
            }
            root.addView(web, 0, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        }
        web?.visibility = View.VISIBLE
        status.visibility = View.GONE
        openButton.visibility = View.GONE
    }

    private fun hideStudio() {
        web?.visibility = View.GONE
        status.visibility = View.VISIBLE
        openButton.visibility = View.VISIBLE
    }

    override fun onDestroy() {
        web?.destroy()
        web = null
        super.onDestroy()
    }

    companion object {
        const val STUDIO = "http://127.0.0.1:${EngineService.PORT}/"
    }
}
