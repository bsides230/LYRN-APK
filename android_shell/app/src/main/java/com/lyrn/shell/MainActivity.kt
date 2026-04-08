package com.lyrn.shell

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

class MainActivity : AppCompatActivity() {
    private lateinit var webViewHost: WebViewHost
    private lateinit var appConfig: AppConfig

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        appConfig = AppConfig(this)

        // Safety check in case setup wasn't completed
        if (!appConfig.isSetupComplete) {
            startActivity(Intent(this, SetupActivity::class.java))
            finish()
            return
        }

        setContentView(R.layout.activity_main)

        // Hide action bar if present
        supportActionBar?.hide()

        val isScreenMode = appConfig.role == AppConfig.ROLE_SCREEN

        // Role-specific configuration
        if (isScreenMode) {
            // Keep screen on for display/viewer mode
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

            // Hide system bars for immersive fullscreen
            val windowInsetsController = WindowCompat.getInsetsController(window, window.decorView)
            windowInsetsController.systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            windowInsetsController.hide(WindowInsetsCompat.Type.systemBars())

            // Setup hidden maintenance entry path (5 taps to reset)
            var tapCount = 0
            val maintenanceTapArea: View = findViewById(R.id.maintenanceTapArea)
            maintenanceTapArea.setOnClickListener {
                tapCount++
                if (tapCount >= 5) {
                    tapCount = 0
                    appConfig.reset()
                    val intent = Intent(this, SetupActivity::class.java)
                    intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
                    startActivity(intent)
                    finish()
                }
            }
        } else {
            // Remote mode doesn't need maintenance tap area
            findViewById<View>(R.id.maintenanceTapArea).visibility = View.GONE
        }

        // Initialize and configure WebView
        webViewHost = WebViewHost(this, findViewById(R.id.webView))

        // Pass the native bridge and role
        val nativeBridge = NativeBridge(this, appConfig)
        webViewHost.setup(nativeBridge, isScreenMode)

        // Load target URL from config
        webViewHost.loadUrl(appConfig.targetUrl)
    }

    override fun onBackPressed() {
        if (appConfig.role == AppConfig.ROLE_SCREEN) {
            // Do not allow back presses in Screen mode to prevent accidental exits
            return
        }

        if (webViewHost.canGoBack()) {
            webViewHost.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
