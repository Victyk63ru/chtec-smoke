package com.qwen.tts.android.reader

/**
 * Splits normalized prose into small, punctuation-aware fragments for Qwen.
 * No AI/network/API is used; all segmentation is deterministic and local.
 */
object BookChunker {
    fun normalize(text: String): String =
        text.replace("\r\n", "\n")
            .replace(Regex("\\s+"), " ")
            .trim()

    fun split(text: String, maxChars: Int = 220): List<String> {
        require(maxChars in 80..500) { "maxChars out of bounds" }
        val source = normalize(text)
        if (source.isEmpty()) return emptyList()
        val chunks = mutableListOf<String>()
        var pos = 0
        while (pos < source.length) {
            val end = minOf(pos + maxChars, source.length)
            if (end == source.length) {
                chunks.add(source.substring(pos))
                break
            }
            val slice = source.substring(pos, end)
            // Prefer end of sentence / phrase, but do not create tiny chunks.
            val minCut = maxChars / 3
            val punct = slice.indexOfLast { it in ".!?;:" }
            val space = slice.lastIndexOf(' ')
            val cut = when {
                punct >= minCut && punct + 1 < maxChars -> punct + 1
                space >= minCut -> space
                else -> maxChars
            }
            val chunk = source.substring(pos, pos + cut).trim()
            if (chunk.isNotEmpty()) chunks.add(chunk)
            pos += cut
            while (pos < source.length && source[pos] == ' ') pos++
        }
        require(chunks.all { it.length <= maxChars }) { "Chunk oversize" }
        return chunks
    }
}
