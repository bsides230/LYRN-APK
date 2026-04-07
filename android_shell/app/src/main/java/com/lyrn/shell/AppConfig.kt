package com.lyrn.shell

import android.content.Context
import android.content.SharedPreferences

class AppConfig(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var isSetupComplete: Boolean
        get() = prefs.getBoolean(KEY_SETUP_COMPLETE, false)
        set(value) = prefs.edit().putBoolean(KEY_SETUP_COMPLETE, value).apply()

    var role: String
        get() = prefs.getString(KEY_ROLE, ROLE_REMOTE) ?: ROLE_REMOTE
        set(value) = prefs.edit().putString(KEY_ROLE, value).apply()

    var targetUrl: String
        get() = prefs.getString(KEY_TARGET_URL, DEFAULT_URL) ?: DEFAULT_URL
        set(value) = prefs.edit().putString(KEY_TARGET_URL, value).apply()

    fun reset() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val PREFS_NAME = "lyrn_shell_config"
        private const val KEY_SETUP_COMPLETE = "setup_complete"
        private const val KEY_ROLE = "role"
        private const val KEY_TARGET_URL = "target_url"

        const val ROLE_REMOTE = "remote"
        const val ROLE_SCREEN = "screen"
        const val DEFAULT_URL = "http://10.0.2.2:8080/"
    }
}
