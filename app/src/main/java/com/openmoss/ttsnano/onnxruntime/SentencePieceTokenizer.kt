package com.openmoss.ttsnano.onnxruntime

import com.sentencepiece.Model
import com.sentencepiece.Scoring
import com.sentencepiece.SentencePieceAlgorithm
import java.io.File

/** Needs token-by-token comparison with the upstream Python tokenizer before A2 is accepted. */
class SentencePieceTokenizer(modelFile: File) {
    private val model = Model.parseFrom(modelFile.toPath())
    private val algorithm = SentencePieceAlgorithm(true, Scoring.HIGHEST_SCORE)
    fun encode(text: String): IntArray = model.encodeNormalized(text, algorithm).map { it.toInt() }.toIntArray()
}
