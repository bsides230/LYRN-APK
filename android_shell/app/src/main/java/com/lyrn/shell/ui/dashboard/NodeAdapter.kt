package com.lyrn.shell.ui.dashboard

import android.graphics.Color
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.lyrn.shell.R
import com.lyrn.shell.model.Node

class NodeAdapter(
    private var nodes: List<Node>,
    private val onEditClick: (Node) -> Unit,
    private val onDeleteClick: (Node) -> Unit,
    private val onNodeClick: (Node) -> Unit
) : RecyclerView.Adapter<NodeAdapter.NodeViewHolder>() {

    private val nodeStatuses = mutableMapOf<String, Boolean>()

    class NodeViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val colorIndicator: View = view.findViewById(R.id.colorIndicator)
        val tvNodeName: TextView = view.findViewById(R.id.tvNodeName)
        val tvCategory: TextView = view.findViewById(R.id.tvCategory)
        val tvNodeUrl: TextView = view.findViewById(R.id.tvNodeUrl)
        val tvNodeRole: TextView = view.findViewById(R.id.tvNodeRole)
        val statusIndicator: View = view.findViewById(R.id.statusIndicator)
        val tvStatusText: TextView = view.findViewById(R.id.tvStatusText)
        val ivEdit: ImageView = view.findViewById(R.id.ivEdit)
        val ivDelete: ImageView = view.findViewById(R.id.ivDelete)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): NodeViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_node_card, parent, false)
        return NodeViewHolder(view)
    }

    override fun onBindViewHolder(holder: NodeViewHolder, position: Int) {
        val node = nodes[position]
        holder.tvNodeName.text = node.name
        holder.tvCategory.text = "Category: ${node.category}"
        holder.tvNodeUrl.text = node.url
        holder.tvNodeRole.text = "Role: ${node.role}"

        try {
            holder.colorIndicator.setBackgroundColor(Color.parseColor(node.color))
        } catch (e: IllegalArgumentException) {
            holder.colorIndicator.setBackgroundColor(Color.LTGRAY)
        }

        val isOnline = nodeStatuses[node.id]
        if (isOnline == null) {
            holder.statusIndicator.backgroundTintList = android.content.res.ColorStateList.valueOf(Color.GRAY)
            holder.tvStatusText.text = "Checking..."
            holder.tvStatusText.setTextColor(Color.DKGRAY)
        } else if (isOnline) {
            holder.statusIndicator.backgroundTintList = android.content.res.ColorStateList.valueOf(Color.GREEN)
            holder.tvStatusText.text = "Online"
            holder.tvStatusText.setTextColor(Color.rgb(0, 150, 0)) // Dark green
        } else {
            holder.statusIndicator.backgroundTintList = android.content.res.ColorStateList.valueOf(Color.RED)
            holder.tvStatusText.text = "Offline"
            holder.tvStatusText.setTextColor(Color.RED)
        }

        holder.ivEdit.setOnClickListener { onEditClick(node) }
        holder.ivDelete.setOnClickListener { onDeleteClick(node) }
        holder.itemView.setOnClickListener { onNodeClick(node) }
    }

    override fun getItemCount() = nodes.size

    fun updateNodes(newNodes: List<Node>) {
        nodes = newNodes
        notifyDataSetChanged()
    }

    fun updateNodeStatus(nodeId: String, isOnline: Boolean) {
        if (nodeStatuses[nodeId] != isOnline) {
            nodeStatuses[nodeId] = isOnline
            // Find position
            val position = nodes.indexOfFirst { it.id == nodeId }
            if (position != -1) {
                notifyItemChanged(position)
            }
        }
    }
}
