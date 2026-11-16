package com.qwen.tts.android.reader

import org.junit.Assert.*
import org.junit.Test
import java.io.File

class BookWavWriterTest {
    @Test fun chunksProduceValidWavCheckpoints() {
        val f=File.createTempFile("chtec_wav_", ".wav")
        try {
            val w=BookWavWriter(f, 24_000)
            w.append(FloatArray(2400){0.1f})
            assertEquals(0.1, BookWavWriter.verifiedDuration(f)!!, 0.001)
            w.append(FloatArray(4800){-0.2f})
            assertEquals(0.3, BookWavWriter.verifiedDuration(f)!!, 0.001)
            w.close()
            assertEquals(44L + 14400L, f.length())
        } finally { f.delete() }
    }
    @Test fun emptyFileIsNotPublished() {
        val f=File.createTempFile("chtec_empty_", ".wav")
        try {
            assertNull(BookWavWriter.verifiedDuration(f))
        } finally { f.delete() }
    }
}
