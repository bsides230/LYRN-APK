package com.lyrn.shell

import android.annotation.SuppressLint
import android.content.Context
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient

class WebViewHost(private val context: Context, private val webView: WebView) {

    @SuppressLint("SetJavaScriptEnabled")
    fun setup() {
        val settings: WebSettings = webView.settings

        // Essential settings for modern web apps
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.databaseEnabled = true
        settings.mediaPlaybackRequiresUserGesture = false
        settings.useWideViewPort = true
        settings.loadWithOverviewMode = true

        // Caching strategy
        settings.cacheMode = WebSettings.LOAD_DEFAULT

        // Allow file access (if needed for local assets)
        settings.allowFileAccess = true

        // Set clients
        webView.webViewClient = WebViewClient()
        webView.webChromeClient = WebChromeClient()
    }

    fun loadUrl(url: String) {
        webView.loadUrl(url)
    }

    fun canGoBack(): Boolean {
        return webView.canGoBack()
    }

    fun goBack() {
        webView.goBack()
    }
}
