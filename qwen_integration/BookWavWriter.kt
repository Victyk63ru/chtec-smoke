package com.qwen.tts.android.reader

import java.io.Closeable
import java.io.File
import java.io.RandomAccessFile

/** PCM16 WAV streaming writer; the full 5-minute audio never accumulates in RAM. */
class BookWavWriter(file: File, private val sampleRate: Int) : Closeable {
    private val io = RandomAccessFile(file, "rw")
    private var samplesWritten = 0L
    val seconds: Double get() = samplesWritten.toDouble() / sampleRate

    init {
        require(sampleRate in 8_000..96_000) { "Unexpected sample rate" }
        io.setLength(0)
        io.write(ByteArray(44))
    }

    fun append(samples: FloatArray) {
        require(samplesWritten + samples.size <= 50_000_000L) { "WAV reached safety size limit" }
        val buffer = ByteArray(8192)
        var offset = 0
        while (offset < samples.size) {
            val count = minOf(buffer.size / 2, samples.size - offset)
            for (i in 0 until count) {
                val f = samples[offset + i].coerceIn(-1f, 1f)
                val pcm = (f * 32767f).toInt()
                buffer[i * 2] = pcm.toByte()
                buffer[i * 2 + 1] = (pcm shr 8).toByte()
            }
            io.write(buffer, 0, count * 2)
            offset += count
        }
        samplesWritten += samples.size
    }

    override fun close() {
        try {
            val dataBytes = samplesWritten * 2
            require(dataBytes <= Int.MAX_VALUE - 44L) { "WAV too long" }
            io.seek(0L)
            ascii("RIFF")
            leInt((dataBytes + 36).toInt())
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
            leInt(dataBytes.toInt())
        } finally {
            io.close()
        }
    }

    private fun ascii(s: String) = io.write(s.toByteArray(Charsets.US_ASCII))
    private fun leShort(n: Int) {
        io.write(n and 255)
        io.write((n ushr 8) and 255)
    }
    private fun leInt(n: Int) {
        io.write(n and 255)
        io.write((n ushr 8) and 255)
        io.write((n ushr 16) and 255)
        io.write((n ushr 24) and 255)
    }
}
