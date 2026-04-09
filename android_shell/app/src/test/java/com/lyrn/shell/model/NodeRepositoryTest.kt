package com.lyrn.shell.model

import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class NodeRepositoryTest {

    private lateinit var repository: NodeRepository

    @Before
    fun setup() {
        repository = NodeRepository(ApplicationProvider.getApplicationContext())
        repository.clear()
    }

    @After
    fun teardown() {
        repository.clear()
    }

    @Test
    fun testAddAndRetrieveNodes() {
        assertTrue(repository.getNodes().isEmpty())

        val node1 = Node(name = "Node 1", url = "http://192.168.1.1")
        repository.addNode(node1)

        var nodes = repository.getNodes()
        assertEquals(1, nodes.size)
        assertEquals("Node 1", nodes[0].name)
        assertEquals("http://192.168.1.1", nodes[0].url)
        assertEquals(node1.id, nodes[0].id)

        val node2 = Node(name = "Node 2", url = "http://192.168.1.2")
        repository.addNode(node2)

        nodes = repository.getNodes()
        assertEquals(2, nodes.size)
    }

    @Test
    fun testUpdateNode() {
        val node = Node(name = "Original Name", url = "http://original")
        repository.addNode(node)

        val nodes = repository.getNodes()
        val savedNode = nodes[0]
        savedNode.name = "Updated Name"
        savedNode.url = "http://updated"

        repository.updateNode(savedNode)

        val updatedNodes = repository.getNodes()
        assertEquals(1, updatedNodes.size)
        assertEquals("Updated Name", updatedNodes[0].name)
        assertEquals("http://updated", updatedNodes[0].url)
        assertEquals(node.id, updatedNodes[0].id)
    }

    @Test
    fun testDeleteNode() {
        val node1 = Node(name = "Node 1", url = "http://192.168.1.1")
        val node2 = Node(name = "Node 2", url = "http://192.168.1.2")
        repository.addNode(node1)
        repository.addNode(node2)

        assertEquals(2, repository.getNodes().size)

        repository.deleteNode(node1.id)

        val nodes = repository.getNodes()
        assertEquals(1, nodes.size)
        assertEquals("Node 2", nodes[0].name)
    }
}
