package com.qwen.tts.android.reader

import android.content.Context
import android.net.Uri
import com.tom_roush.pdfbox.android.PDFBoxResourceLoader
import com.tom_roush.pdfbox.pdmodel.PDDocument
import com.tom_roush.pdfbox.text.PDFTextStripper
import java.io.File

/** Text extraction only (PDF with a text layer or UTF-8 TXT). Not OCR, not a PDF page viewer. */
object BookTextReader {
    const val MAX_SOURCE_BYTES = 35L * 1024L * 1024L
    const val MAX_TEXT_CHARS = 35_000
    const val MAX_PDF_PAGES = 300

    fun read(context: Context, uri: Uri): String {
        val mime = context.contentResolver.getType(uri).orEmpty().lowercase()
        val tmp = File.createTempFile("reader_import_", ".bin", context.cacheDir)
        try {
            val input = context.contentResolver.openInputStream(uri)
                ?: error("Не удалось открыть документ")
            input.use { stream ->
                tmp.outputStream().use { dest ->
                    val bytes = ByteArray(64 * 1024)
                    var total = 0L
                    while (true) {
                        val count = stream.read(bytes)
                        if (count == -1) break
                        total += count
                        require(total <= MAX_SOURCE_BYTES) { "Файл больше 35 МБ. Для теста выбери меньший PDF/TXT." }
                        dest.write(bytes, 0, count)
                    }
                }
            }
            val isPdf = mime == "application/pdf" || tmp.inputStream().use { inp ->
                val header = ByteArray(5)
                inp.read(header) == 5 && header.contentEquals("%PDF-".toByteArray(Charsets.US_ASCII))
            }
            val text = if (isPdf) readPdf(context, tmp) else readTxt(tmp)
            val normalized = BookChunker.normalize(text)
            require(normalized.length >= 40) {
                "Текст не извлечён. Сканированный PDF без текстового слоя пока не поддерживается."
            }
            return normalized.take(MAX_TEXT_CHARS)
        } finally {
            tmp.delete()
        }
    }

    private fun readTxt(tmp: File): String {
        val text = tmp.readText(Charsets.UTF_8)
        require(!text.contains('\uFFFD')) {
            "Файл TXT должен быть в UTF-8. Формат Windows-1251 пока не поддерживается."
        }
        return text.take(MAX_TEXT_CHARS)
    }

    private fun readPdf(context: Context, tmp: File): String {
        PDFBoxResourceLoader.init(context.applicationContext)
        PDDocument.load(tmp).use { document ->
            require(!document.isEncrypted) { "Зашифрованные PDF пока не поддерживаются" }
            val stripper = PDFTextStripper()
            val result = StringBuilder()
            for (p in 1..minOf(MAX_PDF_PAGES, document.numberOfPages)) {
                stripper.startPage = p
                stripper.endPage = p
                result.append(stripper.getText(document)).append('\n')
                if (result.length >= MAX_TEXT_CHARS) break
            }
            return result.toString().take(MAX_TEXT_CHARS)
        }
    }
}
