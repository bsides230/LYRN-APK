package com.lyrn.shell

import android.content.Context
import android.content.SharedPreferences
import com.lyrn.shell.model.Node
import com.lyrn.shell.model.NodeRepository

class AppConfig(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val nodeRepository = NodeRepository(context)

    init {
        migrateOldConfigIfNeeded()
    }

    private fun migrateOldConfigIfNeeded() {
        if (prefs.contains(KEY_TARGET_URL) || prefs.contains(KEY_ROLE)) {
            val oldUrl = prefs.getString(KEY_TARGET_URL, DEFAULT_URL) ?: DEFAULT_URL
            val oldRole = prefs.getString(KEY_ROLE, ROLE_REMOTE) ?: ROLE_REMOTE

            // Only migrate if we don't already have nodes
            if (nodeRepository.getNodes().isEmpty()) {
                val migratedNode = Node(
                    name = "Default Node",
                    url = oldUrl,
                    role = oldRole,
                    category = "Migrated"
                )
                nodeRepository.addNode(migratedNode)
            }

            // Clean up old keys so we don't migrate again
            prefs.edit()
                .remove(KEY_TARGET_URL)
                .remove(KEY_ROLE)
                .apply()
        }
    }

    var isSetupComplete: Boolean
        get() = prefs.getBoolean(KEY_SETUP_COMPLETE, false)
        set(value) = prefs.edit().putBoolean(KEY_SETUP_COMPLETE, value).apply()

    // Temporary backward compatibility for existing code that uses role/targetUrl
    // These now point to the first node in the repository (if it exists)
    var role: String
        get() = nodeRepository.getNodes().firstOrNull()?.role ?: ROLE_REMOTE
        set(value) {
            val nodes = nodeRepository.getNodes()
            if (nodes.isNotEmpty()) {
                val node = nodes[0]
                node.role = value
                nodeRepository.updateNode(node)
            } else {
                val newNode = Node(name = "Default Node", url = DEFAULT_URL, role = value)
                nodeRepository.addNode(newNode)
            }
        }

    var targetUrl: String
        get() = nodeRepository.getNodes().firstOrNull()?.url ?: DEFAULT_URL
        set(value) {
            val nodes = nodeRepository.getNodes()
            if (nodes.isNotEmpty()) {
                val node = nodes[0]
                node.url = value
                nodeRepository.updateNode(node)
            } else {
                val newNode = Node(name = "Default Node", url = value, role = ROLE_REMOTE)
                nodeRepository.addNode(newNode)
            }
        }

    fun reset() {
        prefs.edit().clear().apply()
        nodeRepository.clear()
    }

    companion object {
        private const val PREFS_NAME = "lyrn_shell_config"
        private const val KEY_SETUP_COMPLETE = "setup_complete"
        // Legacy keys
        private const val KEY_ROLE = "role"
        private const val KEY_TARGET_URL = "target_url"

        const val ROLE_REMOTE = "remote"
        const val ROLE_SCREEN = "screen"
        const val DEFAULT_URL = "http://10.0.2.2:8080/"
    }
}
