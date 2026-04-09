package com.lyrn.shell.ui.dashboard

import android.app.AlertDialog
import android.os.Bundle
import android.util.Log
import android.view.LayoutInflater
import android.widget.EditText
import android.widget.RadioButton
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.floatingactionbutton.FloatingActionButton
import com.lyrn.shell.AppConfig
import com.lyrn.shell.R
import com.lyrn.shell.model.Node
import com.lyrn.shell.model.NodeRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

class DashboardActivity : AppCompatActivity() {

    private lateinit var nodeRepository: NodeRepository
    private lateinit var nodeAdapter: NodeAdapter
    private var pingJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_dashboard)

        nodeRepository = NodeRepository(this)

        setupRecyclerView()

        findViewById<FloatingActionButton>(R.id.fabAddNode).setOnClickListener {
            showEditNodeDialog(null)
        }
    }

    override fun onResume() {
        super.onResume()
        refreshNodeList()
        startPingingNodes()
    }

    override fun onPause() {
        super.onPause()
        stopPingingNodes()
    }

    private fun startPingingNodes() {
        pingJob?.cancel()
        pingJob = lifecycleScope.launch {
            while (isActive) {
                val nodes = nodeRepository.getNodes()
                nodes.forEach { node ->
                    launch {
                        val isOnline = pingNode(node.url)
                        withContext(Dispatchers.Main) {
                            nodeAdapter.updateNodeStatus(node.id, isOnline)
                        }
                    }
                }
                delay(5000) // Ping every 5 seconds
            }
        }
    }

    private fun stopPingingNodes() {
        pingJob?.cancel()
        pingJob = null
    }

    private suspend fun pingNode(urlString: String): Boolean = withContext(Dispatchers.IO) {
        try {
            val url = URL(urlString)
            val connection = url.openConnection() as HttpURLConnection
            connection.requestMethod = "HEAD"
            connection.connectTimeout = 3000 // 3 seconds
            connection.readTimeout = 3000

            val responseCode = connection.responseCode
            connection.disconnect()

            responseCode in 200..399
        } catch (e: Exception) {
            Log.e("DashboardActivity", "Failed to ping $urlString: ${e.message}")
            false
        }
    }

    private fun setupRecyclerView() {
        val recyclerView = findViewById<RecyclerView>(R.id.recyclerViewNodes)
        recyclerView.layoutManager = LinearLayoutManager(this)

        nodeAdapter = NodeAdapter(
            nodes = emptyList(),
            onEditClick = { node -> showEditNodeDialog(node) },
            onDeleteClick = { node -> showDeleteConfirmation(node) },
            onNodeClick = { node ->
                val intent = android.content.Intent(this, com.lyrn.shell.MainActivity::class.java).apply {
                    putExtra(com.lyrn.shell.MainActivity.EXTRA_URL, node.url)
                    putExtra(com.lyrn.shell.MainActivity.EXTRA_ROLE, node.role)
                }
                startActivity(intent)
            }
        )
        recyclerView.adapter = nodeAdapter
    }

    private fun refreshNodeList() {
        val nodes = nodeRepository.getNodes()
        nodeAdapter.updateNodes(nodes)
    }

    private fun showEditNodeDialog(node: Node?) {
        val view = LayoutInflater.from(this).inflate(R.layout.dialog_node_edit, null)

        val etNodeName = view.findViewById<EditText>(R.id.etNodeName)
        val etNodeUrl = view.findViewById<EditText>(R.id.etNodeUrl)
        val etNodeCategory = view.findViewById<EditText>(R.id.etNodeCategory)
        val etNodeColor = view.findViewById<EditText>(R.id.etNodeColor)

        val rbRemote = view.findViewById<RadioButton>(R.id.rbRemote)
        val rbScreen = view.findViewById<RadioButton>(R.id.rbScreen)

        if (node != null) {
            etNodeName.setText(node.name)
            etNodeUrl.setText(node.url)
            etNodeCategory.setText(node.category)
            etNodeColor.setText(node.color)
            if (node.role == AppConfig.ROLE_SCREEN) {
                rbScreen.isChecked = true
            } else {
                rbRemote.isChecked = true
            }
        } else {
            rbRemote.isChecked = true // Default
            etNodeColor.setText("#CCCCCC") // Default color
        }

        AlertDialog.Builder(this)
            .setTitle(if (node == null) "Add Node" else "Edit Node")
            .setView(view)
            .setPositiveButton("Save") { _, _ ->
                val name = etNodeName.text.toString()
                val url = etNodeUrl.text.toString()
                val category = etNodeCategory.text.toString()
                val color = etNodeColor.text.toString()
                val role = if (rbScreen.isChecked) AppConfig.ROLE_SCREEN else AppConfig.ROLE_REMOTE

                if (name.isNotBlank() && url.isNotBlank()) {
                    if (node == null) {
                        val newNode = Node(
                            name = name,
                            url = url,
                            category = category,
                            color = color,
                            role = role
                        )
                        nodeRepository.addNode(newNode)
                    } else {
                        val updatedNode = node.copy(
                            name = name,
                            url = url,
                            category = category,
                            color = color,
                            role = role
                        )
                        nodeRepository.updateNode(updatedNode)
                    }
                    refreshNodeList()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showDeleteConfirmation(node: Node) {
        AlertDialog.Builder(this)
            .setTitle("Delete Node")
            .setMessage("Are you sure you want to delete '${node.name}'?")
            .setPositiveButton("Delete") { _, _ ->
                nodeRepository.deleteNode(node.id)
                refreshNodeList()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }
}
