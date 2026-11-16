package com.qwen.tts.android.reader

import java.io.Closeable
import java.io.File
import java.io.RandomAccessFile
import java.nio.charset.StandardCharsets

/**
 * Checkpointed PCM16 mono WAV.
 * Every completed callback leaves a valid WAV header and fsyncs data,
 * so a cancelled or killed batch keeps already generated speech.
 */
class BookWavWriter(private val file: File, private val sampleRate: Int) : Closeable {
    private val io: RandomAccessFile
    private var samplesWritten = 0L
    private var closed = false
    val seconds: Double get() = samplesWritten.toDouble() / sampleRate

    init {
        require(sampleRate in 8_000..96_000)
        file.parentFile?.mkdirs()
        io = RandomAccessFile(file, "rw")
        io.setLength(0)
        io.write(ByteArray(44))
        checkpoint()
    }

    @Synchronized fun append(samples: FloatArray) {
        require(!closed) { "WAV writer closed" }
        require(samples.isNotEmpty()) { "Empty audio chunk" }
        require(samplesWritten + samples.size < Int.MAX_VALUE / 2L) { "WAV too large" }
        val bytes = ByteArray(8192)
        var offset = 0
        while (offset < samples.size) {
            val count = minOf(bytes.size / 2, samples.size - offset)
            for (i in 0 until count) {
                val f = samples[offset + i].coerceIn(-1.0f, 1.0f)
                val pcm = (f * 32767f).toInt()
                bytes[i * 2] = pcm.toByte()
                bytes[i * 2 + 1] = (pcm shr 8).toByte()
            }
            io.write(bytes, 0, count * 2)
            offset += count
        }
        samplesWritten += samples.size
        checkpoint()
    }

    private fun checkpoint() {
        val end = io.filePointer
        val payloadSize = samplesWritten * 2
        io.seek(0)
        ascii("RIFF")
        leInt((36 + payloadSize).toInt())
        ascii("WAVE")
        ascii("fmt ")
        leInt(16)
        leShort(1)
        leShort(1)
        leInt(sampleRate)
        leInt(sampleRate * 2)
        leShort(2)
        leShort(16)
        ascii("data")
        leInt(payloadSize.toInt())
        io.seek(end)
        io.fd.sync()
    }

    override fun close() {
        if (closed) return
        try { checkpoint() } finally { closed = true; io.close() }
    }

    private fun ascii(s: String) { io.write(s.toByteArray(StandardCharsets.US_ASCII)) }
    private fun leShort(n: Int) { io.write(n and 255); io.write((n ushr 8) and 255) }
    private fun leInt(n: Int) {
        io.write(n and 255)
        io.write((n ushr 8) and 255)
        io.write((n ushr 16) and 255)
        io.write((n ushr 24) and 255)
    }

    companion object {
        fun verifiedDuration(file: File): Double? {
            if (!file.isFile || file.length() <= 44) return null
            return try {
                RandomAccessFile(file, "r").use { f ->
                    fun four(at: Long): String {
                        f.seek(at)
                        val b = ByteArray(4)
                        f.readFully(b)
                        return String(b, StandardCharsets.US_ASCII)
                    }
                    fun intLE(at: Long): Int {
                        f.seek(at)
                        return Integer.reverseBytes(f.readInt())
                    }
                    if (four(0) != "RIFF" || four(8) != "WAVE" || four(36) != "data") return null
                    val n = intLE(40)
                    val rate = intLE(24)
                    val bytes = f.length() - 44
                    if (n <= 0 || n.toLong() > bytes || rate !in 8_000..96_000) return null
                    n.toDouble() / 2.0 / rate
                }
            } catch (_: Exception) { null }
        }
    }
}
