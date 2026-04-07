package com.lyrn.shell

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {
    private lateinit var webViewHost: WebViewHost

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Hide action bar if present
        supportActionBar?.hide()

        // Initialize and configure WebView
        webViewHost = WebViewHost(this, findViewById(R.id.webView))
        webViewHost.setup()

        // Load target URL (placeholder for later config injection)
        webViewHost.loadUrl("http://10.0.2.2:8080/")
    }

    override fun onBackPressed() {
        if (webViewHost.canGoBack()) {
            webViewHost.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
