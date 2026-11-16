package com.qwen.tts.android.reader

import android.content.Context
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Privacy-preserving local diagnostics. Never includes source book text, voice audio, or model files. */
object ChtecDiagnostics {
    private val lock = Any()
    private var path: File? = null
    private const val LIMIT_BYTES = 128 * 1024

    fun initialize(context: Context) {
        synchronized(lock) {
            if (path == null) {
                path = File(context.applicationContext.filesDir, "chtec_diagnostics.txt")
            }
        }
        record("APP", "started")
    }

    fun record(category: String, details: String) {
        synchronized(lock) {
            val file = path ?: return
            try {
                val safeType = category.replace(Regex("[^A-Za-z0-9_.-]"), "").take(40)
                val safeText = details.replace('\r', ' ').replace('\n', ' ').take(400)
                val time = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())
                file.appendText("[$time] $safeType: $safeText\n")
                if (file.length() > LIMIT_BYTES) {
                    file.writeText(file.readText().takeLast(LIMIT_BYTES / 2))
                }
            } catch (_: Exception) {
                // Logging must never crash the synthesis path.
            }
        }
    }

    fun snapshot(): String = synchronized(lock) {
        try {
            path?.takeIf { it.exists() }?.readText().orEmpty()
        } catch (e: Exception) {
            "Не удалось открыть журнал: " + (e.message ?: e.javaClass.simpleName)
        }
    }
}
