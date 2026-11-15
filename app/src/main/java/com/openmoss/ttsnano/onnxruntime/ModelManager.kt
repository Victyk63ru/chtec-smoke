package com.openmoss.ttsnano.onnxruntime

import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Downloads model files once, validates known SHA-256s and streams the response.
 * SHA values are candidates supplied from a previous research report; confirm against
 * pinned Hugging Face revision before shipping any public app.
 * This is a technical smoke-test downloader, not a production update system.
 */
object ModelManager {
    private data class Asset(val repo: String, val name: String, val minBytes: Long = 1024L, val sha256: String? = null)
    private const val HF_TTS = "OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX"
    private const val HF_CODEC = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"
    private val assets = listOf(
        Asset(HF_TTS, "browser_poc_manifest.json", 100_000),
        Asset(HF_TTS, "tts_browser_onnx_meta.json", 100),
        Asset(HF_TTS, "tokenizer.model", 100_000, "c353ee1479b536bf414c1b247f5542b6607fb8ae91320e5af1781fee200fddff"),
        Asset(HF_TTS, "moss_tts_prefill.onnx", 100_000, "d56126dcd0574c2f15d98fc6b35eda68d0386b5bd9c5e38e28548d6f2ea8f3db"),
        Asset(HF_TTS, "moss_tts_decode_step.onnx", 100_000, "698cbc2fc1c2feca16e5895614ed52bbb32ded10f236c076f477b2e69abf32d8"),
        Asset(HF_TTS, "moss_tts_local_fixed_sampled_frame.onnx", 100_000, "40cdb00efc171c450cf91468e01429caa41b0252222cd308e978f58fe354afa8"),
        Asset(HF_TTS, "moss_tts_global_shared.data", 400_000_000, "bce8312c3df6a44545302cae229b61054fe0672e0b252ba59cba47adeed831dc"),
        Asset(HF_TTS, "moss_tts_local_shared.data", 200_000_000, "bae7782032c0fb12490ab42afe009f87ae6c75a0f0596fc7b5c08e4d5ee93916"),
        Asset(HF_CODEC, "codec_browser_onnx_meta.json", 100),
        Asset(HF_CODEC, "moss_audio_tokenizer_decode_full.onnx", 100_000, "0fbbafe3fd4afa2a019af5c5ced204af6e2d1db044fa40f021525d2aee95b4ac"),
        Asset(HF_CODEC, "moss_audio_tokenizer_decode_shared.data", 40_000_000, "e69d52e0f4e84ca27850557ee54face46632d3a5a16c89bd246c7c408466dcad")
    )

    fun ensureModels(root: File, progress: (String) -> Unit) {
        require(root.exists() || root.mkdirs()) { "Нельзя создать папку моделей" }
        // Approximate sizes only for a conservative free-space check; NOT authoritative file metadata.
        val estimates = mapOf(
            "browser_poc_manifest.json" to 503_000L,
            "tts_browser_onnx_meta.json" to 5_000L,
            "tokenizer.model" to 471_000L,
            "moss_tts_prefill.onnx" to 283_000L,
            "moss_tts_decode_step.onnx" to 291_000L,
            "moss_tts_local_fixed_sampled_frame.onnx" to 471_000L,
            "moss_tts_global_shared.data" to 441_000_000L,
            "moss_tts_local_shared.data" to 230_000_000L,
            "codec_browser_onnx_meta.json" to 17_000L,
            "moss_audio_tokenizer_decode_full.onnx" to 682_000L,
            "moss_audio_tokenizer_decode_shared.data" to 44_200_000L
        )
        val missingEstimate = assets.sumOf { asset ->
            val target = destination(root, asset)
            if (target.isFile && target.length() >= asset.minBytes) 0L else {
                val part = File(target.parentFile, "${target.name}.part")
                ((estimates[asset.name] ?: asset.minBytes) - part.length()).coerceAtLeast(0L)
            }
        }
        if (missingEstimate > 0 && root.usableSpace < missingEstimate + 50_000_000L) {
            error("Недостаточно свободного места для недостающих файлов: нужно ещё примерно ${missingEstimate / 1_000_000L + 50} МБ")
        }
        assets.forEachIndexed { index, asset ->
            val target = destination(root, asset)
            target.parentFile?.mkdirs()
            if (target.isFile && isValid(target, asset)) {
                progress("${index + 1}/${assets.size}: готово ${asset.name}")
                return@forEachIndexed
            }
            if (target.exists()) target.delete()
            progress("${index + 1}/${assets.size}: скачиваю ${asset.name}")
            val url = "https://huggingface.co/${asset.repo}/resolve/main/${asset.name}"
            fetchResume(url, target, asset)
            require(isValid(target, asset)) { "Контрольная проверка не пройдена: ${asset.name}" }
        }
    }

    private fun destination(root: File, asset: Asset): File {
        val folder = if (asset.repo == HF_TTS) "MOSS-TTS-Nano-100M-ONNX" else "MOSS-Audio-Tokenizer-Nano-ONNX"
        return File(File(root, folder), asset.name)
    }

    private fun isValid(file: File, asset: Asset): Boolean {
        if (!file.isFile || file.length() < asset.minBytes) return false
        return asset.sha256 == null || sha256(file).equals(asset.sha256, ignoreCase = true)
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(32768)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                digest.update(buffer, 0, n)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun fetchResume(url: String, target: File, asset: Asset) {
        val part = File(target.parentFile, "${target.name}.part")
        var already = if (part.exists()) part.length() else 0L
        var conn = connect(url, already)
        try {
            val response = conn.responseCode
            if (response == 206 && already > 0) {
                val range = conn.getHeaderField("Content-Range")
                val beginning = Regex("^bytes (\\d+)-\\d+/(\\d+|\\*)$")
                    .matchEntire(range ?: "")?.groupValues?.get(1)?.toLongOrNull()
                if (beginning != already) error("Некорректный Content-Range: $range")
            } else if (response == 200) {
                already = 0L // HTTP server ignored Range: overwrite .part from start
            } else if (response == 416) {
                // Stale or complete partial file; retry from scratch.
                conn.disconnect()
                part.delete()
                conn = connect(url, 0)
                already = 0L
                if (conn.responseCode != 200) error("HTTP ${conn.responseCode}: ${asset.name}")
            } else {
                error("HTTP $response: ${asset.name}")
            }
            conn.inputStream.use { input ->
                FileOutputStream(part, already > 0).buffered().use { output ->
                    input.copyTo(output, 32768)
                }
            }
        } finally { conn.disconnect() }
        require(isValid(part, asset)) { "Неполный/неверный файл ${asset.name}. Повторите загрузку." }
        if (!part.renameTo(target)) error("Не удалось сохранить ${asset.name}")
    }

    private fun connect(url: String, from: Long): HttpURLConnection {
        return (URL(url).openConnection() as HttpURLConnection).apply {
            instanceFollowRedirects = true
            connectTimeout = 30_000
            readTimeout = 180_000
            setRequestProperty("Accept-Encoding", "identity")
            if (from > 0) setRequestProperty("Range", "bytes=$from-")
        }
    }
}
