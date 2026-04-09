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

        return config.toString()
    }

    @JavascriptInterface
    fun resetConfig() {
        appConfig.reset()
        val intent = Intent(context, com.lyrn.shell.ui.dashboard.DashboardActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        context.startActivity(intent)
    }
}
