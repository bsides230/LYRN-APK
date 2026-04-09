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

        // Setup functionality migrated to DashboardActivity, skipping SetupActivity launch

        setContentView(R.layout.activity_main)

        // Hide action bar if present
        supportActionBar?.hide()

        // Remote mode doesn't need maintenance tap area
        findViewById<View>(R.id.maintenanceTapArea).visibility = View.GONE

        // Initialize and configure WebView
        webViewHost = WebViewHost(this, findViewById(R.id.webView))

        // Pass the native bridge and role
        val nativeBridge = NativeBridge(this, appConfig)
        webViewHost.setup(nativeBridge)

        // Load target URL from config
        webViewHost.loadUrl(appConfig.targetUrl)
    }

    override fun onBackPressed() {
        if (webViewHost.canGoBack()) {
            webViewHost.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
