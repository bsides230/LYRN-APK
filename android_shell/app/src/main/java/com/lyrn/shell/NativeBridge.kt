package com.lyrn.shell

import android.content.Context
import android.content.Intent
import android.webkit.JavascriptInterface
import org.json.JSONObject

class NativeBridge(private val context: Context, private val appConfig: AppConfig) {

    @JavascriptInterface
    fun getConfig(): String {
        val config = JSONObject()
        config.put("role", appConfig.role)
        config.put("targetUrl", appConfig.targetUrl)

        // Add screen mode specific configuration
        val isScreen = appConfig.role == AppConfig.ROLE_SCREEN
        config.put("isScreenMode", isScreen)

        return config.toString()
    }

    @JavascriptInterface
    fun resetConfig() {
        appConfig.reset()
        val intent = Intent(context, SetupActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        context.startActivity(intent)
    }
}
