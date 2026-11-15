package com.openmoss.ttsnano.onnxruntime

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.io.File
import java.nio.FloatBuffer
import java.nio.IntBuffer
import kotlin.math.min

/**
 * Stage B: user WAV -> local ONNX audio encoder -> prompt audio codes.
 * Based on OpenMOSS onnx_tts_runtime.py encode_reference_audio.
 * No voice file or embeddings are sent over a network.
 */
object VoiceProfileEncoder {
    fun encode(modelRoot: File, reference: File): List<IntArray> {
        val wav = VoiceReferenceWav.read(reference)
        val encoderPath = File(
            modelRoot,
            "MOSS-Audio-Tokenizer-Nano-ONNX/moss_audio_tokenizer_encode.onnx"
        )
        require(encoderPath.isFile) { "Не загружен ONNX-энкодер личного голоса" }
        val env = OrtEnvironment.getEnvironment()
        val options = OrtSession.SessionOptions()
        options.setIntraOpNumThreads(2)
        try {
            env.createSession(encoderPath.absolutePath, options).use { session ->
                OnnxTensor.createTensor(
                    env,
                    FloatBuffer.wrap(wav.channelsFirstStereo),
                    longArrayOf(1L, 2L, wav.frameCount.toLong())
                ).use { waveform ->
                    OnnxTensor.createTensor(
                        env,
                        IntBuffer.wrap(intArrayOf(wav.frameCount)),
                        longArrayOf(1L)
                    ).use { lengths ->
                        session.run(mapOf(
                            "waveform" to waveform,
                            "input_lengths" to lengths
                        )).use { out ->
                            val codesValue = out.get("audio_codes")
                                .orElseThrow { IllegalStateException("Нет выхода audio_codes") }
                            val lengthsValue = out.get("audio_code_lengths")
                                .orElseThrow { IllegalStateException("Нет выхода audio_code_lengths") }
                            val codes = codesValue.value as? Array<*>
                                ?: error("Некорректная форма audio_codes")
                            val frames = codes.firstOrNull() as? Array<*>
                                ?: error("Некорректный пакет audio_codes")
                            val count = intFirst(lengthsValue.value)
                            require(count in 1..frames.size) { "Некорректная длина аудио-кодов: $count" }
                            val result = (0 until count).map { frame ->
                                val row = frames[frame] as? IntArray
                                    ?: error("Некорректная строка audio_codes $frame")
                                require(row.size == 16) { "Ожидалось 16 кодеков, получено ${row.size}" }
                                row.copyOf()
                            }
                            require(result.isNotEmpty()) { "Звуковые токены не созданы" }
                            return result
                        }
                    }
                }
            }
        } finally {
            options.close()
        }
    }

    private fun intFirst(value: Any?): Int = when(value) {
        is Int -> value
        is Number -> value.toInt()
        is IntArray -> value.firstOrNull() ?: error("Пустая длина")
        is LongArray -> value.firstOrNull()?.toInt() ?: error("Пустая длина")
        is Array<*> -> intFirst(value.firstOrNull())
        else -> error("Неизвестная форма audio_code_lengths: ${value?.javaClass?.name}")
    }
}
