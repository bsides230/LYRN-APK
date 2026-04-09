package com.lyrn.shell.model

import android.content.Context
import android.content.SharedPreferences
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

class NodeRepository(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val gson = Gson()

    fun getNodes(): List<Node> {
        val json = prefs.getString(KEY_NODES, null) ?: return emptyList()
        val type = object : TypeToken<List<Node>>() {}.type
        return try {
            gson.fromJson(json, type) ?: emptyList()
        } catch (e: Exception) {
            emptyList()
        }
    }

    private fun saveNodes(nodes: List<Node>) {
        val json = gson.toJson(nodes)
        prefs.edit().putString(KEY_NODES, json).apply()
    }

    fun addNode(node: Node) {
        val nodes = getNodes().toMutableList()
        nodes.add(node)
        saveNodes(nodes)
    }

    fun updateNode(updatedNode: Node) {
        val nodes = getNodes().toMutableList()
        val index = nodes.indexOfFirst { it.id == updatedNode.id }
        if (index != -1) {
            nodes[index] = updatedNode
            saveNodes(nodes)
        }
    }

    fun deleteNode(nodeId: String) {
        val nodes = getNodes().toMutableList()
        nodes.removeAll { it.id == nodeId }
        saveNodes(nodes)
    }

    fun clear() {
        prefs.edit().remove(KEY_NODES).apply()
    }

    companion object {
        private const val PREFS_NAME = "lyrn_nodes_config"
        private const val KEY_NODES = "nodes_list"
    }
}
