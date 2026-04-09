package com.lyrn.shell

import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
    private lateinit var webViewHost: WebViewHost

    companion object {
        const val EXTRA_URL = "extra_url"
        const val EXTRA_ROLE = "extra_role"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Hide action bar if present
        supportActionBar?.hide()

        // Extract URL and Role from Intent
        val targetUrl = intent.getStringExtra(EXTRA_URL)
        val role = intent.getStringExtra(EXTRA_ROLE)

        if (targetUrl == null || role == null) {
            Toast.makeText(this, "Error: Missing URL or Role", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        // Remote mode doesn't need maintenance tap area
        findViewById<View>(R.id.maintenanceTapArea).visibility = View.GONE

        // Initialize and configure WebView
        webViewHost = WebViewHost(this, findViewById(R.id.webView))

        // Pass the native bridge and role
        val nativeBridge = NativeBridge(this, role, targetUrl)
        webViewHost.setup(nativeBridge)

        // Load target URL
        webViewHost.loadUrl(targetUrl)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webViewHost.canGoBack()) {
                    webViewHost.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
    }
}
