package com.openmoss.ttsnano.onnxruntime

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.min

/** Strict import for Stage B: RIFF/WAVE PCM16, 48kHz, 1 or 2 channels, max 12 seconds. */
object VoiceReferenceWav {
    data class Data(val channelsFirstStereo: FloatArray, val frameCount: Int)

    fun read(file: File): Data {
        require(file.isFile) { "Образец голоса не найден" }
        require(file.length() in 45..4_800_000L) { "Нужен короткий WAV не более 12 секунд (до 4,8 МБ)" }
        val bytes = file.readBytes()
        val b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        require(bytes.size >= 44 && ascii(bytes, 0) == "RIFF" && ascii(bytes, 8) == "WAVE") {
            "Требуется обычный файл WAV (RIFF)"
        }
        var channels = 0
        var rate = 0
        var bits = 0
        var format = 0
        var dataOffset = -1
        var dataSize = 0
        var at = 12
        while (at + 8 <= bytes.size) {
            val tag = ascii(bytes, at)
            val n = b.getInt(at + 4)
            require(n >= 0 && n.toLong() <= bytes.size.toLong() - at - 8) { "Повреждён WAV: $tag" }
            val start = at + 8
            when (tag) {
                "fmt " -> {
                    require(n >= 16) { "Некорректный fmt WAV" }
                    format = b.getShort(start).toInt() and 0xffff
                    channels = b.getShort(start + 2).toInt() and 0xffff
                    rate = b.getInt(start + 4)
                    bits = b.getShort(start + 14).toInt() and 0xffff
                }
                "data" -> {
                    dataOffset = start
                    dataSize = n
                }
            }
            at = start + n + (n and 1)
        }
        require(format == 1 && bits == 16 && rate == 48000 && channels in 1..2) {
            "Нужен WAV PCM16, 48 кГц, моно или стерео. Получено: формат=$format, $rate Гц, $channels каналов, $bits бит"
        }
        require(dataOffset >= 0 && dataSize > 0) { "В WAV отсутствуют звуковые данные" }
        val count = dataSize / (channels * 2)
        require(count in 24_000..576_000) { "Нужна речь длительностью от 0,5 до 12 секунд" }
        val samples = FloatArray(count * 2)
        for (i in 0 until count) {
            val left = b.getShort(dataOffset + i * channels * 2).toFloat() / 32768f
            val right = if (channels == 2) {
                b.getShort(dataOffset + i * 4 + 2).toFloat() / 32768f
            } else left
            samples[i] = left
            samples[count + i] = right
        }
        return Data(samples, count)
    }

    private fun ascii(data: ByteArray, offset: Int): String =
        String(data, offset, min(4, data.size - offset), Charsets.US_ASCII)
}
