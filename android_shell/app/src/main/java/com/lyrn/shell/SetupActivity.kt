package com.lyrn.shell

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.RadioButton
import android.widget.RadioGroup
import androidx.appcompat.app.AppCompatActivity

class SetupActivity : AppCompatActivity() {
    private lateinit var appConfig: AppConfig

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        appConfig = AppConfig(this)

        if (appConfig.isSetupComplete) {
            launchMainActivity()
            return
        }

        setContentView(R.layout.activity_setup)
        supportActionBar?.hide()

        val rbRemote = findViewById<RadioButton>(R.id.rbRemote)
        val rbScreen = findViewById<RadioButton>(R.id.rbScreen)
        val etUrl = findViewById<EditText>(R.id.etUrl)
        val btnSave = findViewById<Button>(R.id.btnSave)

        // Load existing values if any
        etUrl.setText(appConfig.targetUrl)
        if (appConfig.role == AppConfig.ROLE_SCREEN) {
            rbScreen.isChecked = true
        } else {
            rbRemote.isChecked = true
        }

        btnSave.setOnClickListener {
            val selectedRole = if (rbScreen.isChecked) AppConfig.ROLE_SCREEN else AppConfig.ROLE_REMOTE
            val enteredUrl = etUrl.text.toString().trim()

            val finalUrl = if (enteredUrl.isEmpty()) AppConfig.DEFAULT_URL else enteredUrl

            appConfig.role = selectedRole
            appConfig.targetUrl = finalUrl
            appConfig.isSetupComplete = true

            launchMainActivity()
        }
    }

    private fun launchMainActivity() {
        val intent = Intent(this, MainActivity::class.java)
        startActivity(intent)
        finish()
    }
}
