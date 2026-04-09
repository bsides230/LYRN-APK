package com.lyrn.shell

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.webkit.JavascriptInterface
import org.json.JSONObject

class NativeBridge(
    private val context: Context,
    private val role: String,
    private val targetUrl: String
) {

    @JavascriptInterface
    fun getConfig(): String {
        val config = JSONObject()
        config.put("role", role)
        config.put("targetUrl", targetUrl)

        return config.toString()
    }

    @JavascriptInterface
    fun resetConfig() {
        if (context is Activity) {
            context.runOnUiThread {
                context.finish()
            }
        } else {
            val intent = Intent(context, com.lyrn.shell.ui.dashboard.DashboardActivity::class.java)
            intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
            context.startActivity(intent)
        }
    }
}
