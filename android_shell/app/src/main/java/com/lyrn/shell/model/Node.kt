package com.lyrn.shell.model

import java.util.UUID

data class Node(
    val id: String = UUID.randomUUID().toString(),
    var name: String,
    var url: String,
    var category: String = "Default",
    var color: String = "#CCCCCC",
    var role: String = "remote"
)
