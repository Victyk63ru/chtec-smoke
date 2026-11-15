package com.qwen.tts.android.reader

import org.junit.Assert.*
import org.junit.Test

class BookChunkerTest {
    @Test fun preservesTextAndPunctuation() {
        val cases = listOf(
            "Привет, мир! Как дела? — Хорошо.",
            "Слово ".repeat(300),
            "Здесь длинная строка без пунктуации, но с пробелами. Следующий абзац."
        )
        for (input in cases) {
            val chunks = BookChunker.split(input)
            assertTrue(chunks.isNotEmpty())
            assertTrue(chunks.all { it.length <= 220 })
            assertEquals(BookChunker.normalize(input), chunks.joinToString(" "))
        }
    }
    @Test fun giantUnbrokenWordIsNotLost() {
        val word = "А".repeat(800)
        val result = BookChunker.split(word)
        assertEquals(word, result.joinToString(""))
    }
    @Test fun whitespaceAndBounds() {
        assertTrue(BookChunker.split("  \n\t ").isEmpty())
        assertEquals("а б", BookChunker.split("а  \n б").joinToString(" "))
        try {
            BookChunker.split("Test", 40)
            fail("Expected invalid chunk size rejection")
        } catch (expected: IllegalArgumentException) { }
    }
}
