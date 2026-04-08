package com.lyrn.shell

import android.annotation.SuppressLint
import android.content.Context
import android.webkit.WebChromeClient
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.os.Handler
import android.os.Looper

class WebViewHost(private val context: Context, private val webView: WebView) {

    @SuppressLint("SetJavaScriptEnabled", "ClickableViewAccessibility")
    fun setup(nativeBridge: NativeBridge? = null, isScreenMode: Boolean = false) {
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
        webView.webViewClient = object : WebViewClient() {
            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                super.onReceivedError(view, request, error)
                if (isScreenMode && request?.isForMainFrame == true) {
                    scheduleReload(view, request.url.toString())
                }
            }

            override fun onReceivedHttpError(
                view: WebView?,
                request: WebResourceRequest?,
                errorResponse: android.webkit.WebResourceResponse?
            ) {
                super.onReceivedHttpError(view, request, errorResponse)
                // HTTP errors on main frame (e.g. 502 Bad Gateway) might also need reloading
                if (isScreenMode && request?.isForMainFrame == true) {
                    scheduleReload(view, request.url.toString())
                }
            }
        }
        webView.webChromeClient = WebChromeClient()

        // Inject native bridge
        if (nativeBridge != null) {
            webView.addJavascriptInterface(nativeBridge, "LyrnNative")
        }

        if (isScreenMode) {
            // Prevent accidental interactions
            webView.isHapticFeedbackEnabled = false
            webView.isLongClickable = false
            webView.setOnLongClickListener { true }
            webView.overScrollMode = WebView.OVER_SCROLL_NEVER
        }
    }

    private fun scheduleReload(view: WebView?, url: String) {
        Handler(Looper.getMainLooper()).postDelayed({
            view?.loadUrl(url)
        }, 10000) // 10 seconds
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
