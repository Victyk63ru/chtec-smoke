#!/usr/bin/env python3
"""Stage C: enable already-existing JNI streaming with honest stop, checkpoints,
progress, recovery, and a bounded first test. Never edit qwen3-tts.cpp."""
from pathlib import Path
import shutil
import re

root=Path("upstream")
ui_path=root/"app/src/main/java/com/qwen/tts/android/MainActivity.kt"
q_path=root/"app/src/main/java/com/qwen/tts/studio/engine/QwenEngine.kt"
ui=ui_path.read_text(encoding="utf8")
q=q_path.read_text(encoding="utf8")

def only(text,old,new):
    count=text.count(old)
    if count != 1: raise SystemExit(f"STREAM_PATCH_ABORT match count={count} for {old[:100]!r}")
    return text.replace(old,new)

q=only(q,
    '    fun getLastError(): String? = nativeGetLastError(nativePtr)\n',
    """    /**
     * Uses native streaming symbol already present in pinned qwen3-tts.cpp.
     * Returning false from callback requests cancellation at next audio chunk.
     */
    fun interface AudioChunkCallback {
        fun onAudioChunk(
            samples: FloatArray,
            sampleRate: Int,
            startSample: Long,
            endSample: Long,
            startFrame: Int,
            endFrame: Int,
            startTextByte: Int,
            endTextByte: Int,
            textAlignmentKind: Int,
            confidence: Float,
        ): Boolean
    }

    fun synthesizeStreaming(
        text: String,
        speakerEmbeddingPath: String?,
        params: NativeParams,
        chunkSeconds: Float = 0.32f,
        leftContextSeconds: Float = 0.16f,
        collectAudio: Boolean = false,
        callback: AudioChunkCallback,
    ): NativeResult = nativeSynthesizeStreaming(
        nativePtr, text, null, speakerEmbeddingPath, null,
        params, chunkSeconds, leftContextSeconds, collectAudio, callback,
    )

    fun getLastError(): String? = nativeGetLastError(nativePtr)
""")
q=only(q,
    '    private external fun nativeGetLastError(ptr: Long): String?\n',
    """    private external fun nativeSynthesizeStreaming(
        ptr: Long,
        text: String,
        referenceWav: String?,
        speakerEmbeddingPath: String?,
        iclPromptPath: String?,
        params: NativeParams,
        chunkSeconds: Float,
        leftContextSeconds: Float,
        collectAudio: Boolean,
        callback: AudioChunkCallback,
    ): NativeResult
    private external fun nativeGetLastError(ptr: Long): String?
""")
q_path.write_text(q,encoding="utf8")

start=ui.find("data class BookUiState(")
end=ui.find("class MainViewModel(application: Application)",start)
assert start>=0 and end>start
ui=ui[:start]+"""data class BookUiState(
    val busy: Boolean = false,
    val documentReady: Boolean = false,
    val chars: Int = 0,
    val preview: String = "",
    val chunksDone: Int = 0,
    val chunksTotal: Int = 0,
    val seconds: Double = 0.0,
    val wavReady: Boolean = false,
    val elapsedMs: Long = 0L,
    val frames: Int = 0,
    val rtf: Double = 0.0,
    val stage: String = "idle",
    val status: String = "Открой PDF с текстовым слоем или TXT UTF-8",
    val error: String? = null,
)

"""+ui[end:]

ui=only(ui,
    '    private val readerWav: File get() = File(getApplication<Application>().filesDir, "reader/reader_test.wav")\n',
    """    private val readerWav: File get() = File(getApplication<Application>().filesDir, "reader/reader_test.wav")
    private val readerProgress: File get() = File(getApplication<Application>().filesDir, "reader/reader_progress.wav")
    private var readerTicker: Job? = null
    private fun availableReaderWav(): File? {
        if (BookWavWriter.verifiedDuration(readerProgress) != null) return readerProgress
        if (BookWavWriter.verifiedDuration(readerWav) != null) return readerWav
        return null
    }
""")
# Restore last session's partial or complete audio as exportable on launch.
ui=only(ui,
    '        refreshModelState()\n    }\n',
    """        refreshModelState()
        val rescued = availableReaderWav()
        if (rescued != null) {
            _bookState.update { it.copy(
                wavReady = true,
                seconds = BookWavWriter.verifiedDuration(rescued) ?: 0.0,
                status = "Найден сохранённый WAV предыдущего сеанса. Его можно экспортировать."
            ) }
            ChtecDiagnostics.record("RECOVER", "wav from previous session")
        }
    }
""")
# Locate and replace just the Reader work methods, preserving existing Studio and Voices.
start=ui.find("    fun stopReader() {")
end=ui.find("    fun exportReader(uri: Uri) {",start)
assert start>=0 and end>start
methods=r"""    fun stopReader() {
        if (!_bookState.value.busy) return
        readerCancel = true
        _bookState.update { it.copy(
            status = "Запрошена остановка. Qwen прекратит расчёт при следующем аудиоблоке."
        ) }
        ChtecDiagnostics.record("READER_CANCEL", "requested")
    }

    fun startReader(targetAudioSeconds: Int = 15) {
        if (_bookState.value.busy || _uiState.value.busy) return
        if (readerText.length < 80) {
            _bookState.update { it.copy(error = "Нужен текст от 80 символов") }
            return
        }
        val voice = _uiState.value.selectedVoiceId?.let { id ->
            voices.value.firstOrNull { it.voiceId == id }
        }
        if (voice == null || !File(voice.speakerEmbeddingPath).isFile) {
            _bookState.update { it.copy(error = "Выбери созданный голос в Voices") }
            return
        }
        val variant = selectedVariant()
        if (!isModelReady(variant)) {
            _bookState.update { it.copy(error = "Модель отсутствует. Открой Settings") }
            return
        }
        val goal = targetAudioSeconds.coerceIn(10, 300).toDouble()
        val parts = BookChunker.split(readerText, 96)
        readerCancel = false
        readerProgress.delete() // previous complete WAV remains safe
        val started = SystemClock.elapsedRealtime()
        _bookState.update { it.copy(
            busy = true, error = null, wavReady = availableReaderWav()!=null,
            chunksDone = 0, chunksTotal = parts.size, seconds = 0.0,
            elapsedMs = 0, frames = 0, rtf = 0.0, stage = "load",
            status = "Инициализация модели; цель " + goal.toInt() + " сек аудио"
        ) }
        ChtecDiagnostics.record("STREAM_START", "parts=" + parts.size + " goal_secs=" + goal)
        _uiState.update { it.copy(busy = true) }
        readerTicker?.cancel()
        readerTicker = viewModelScope.launch {
            var lastHeartbeat = 0L
            while (_bookState.value.busy) {
                kotlinx.coroutines.delay(1000L)
                val elapsed = SystemClock.elapsedRealtime() - started
                val audioSeconds = _bookState.value.seconds
                _bookState.update { it.copy(
                    elapsedMs = elapsed,
                    rtf = if (audioSeconds > 0.3) elapsed / 1000.0 / audioSeconds else 0.0
                ) }
                if (elapsed - lastHeartbeat >= 10_000L) {
                    lastHeartbeat = elapsed
                    ChtecDiagnostics.record(
                        "STREAM_HEARTBEAT",
                        "stage=" + _bookState.value.stage +
                        " elapsed_ms=" + elapsed +
                        " frames=" + _bookState.value.frames +
                        " audio_s=" + audioSeconds
                    )
                }
            }
        }
        viewModelScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    val native = ensureEngineLoaded(variant)
                    ChtecDiagnostics.record("STREAM_LOADED", "elapsed_ms=" + (SystemClock.elapsedRealtime()-started))
                    var completedParts = 0
                    var callbacks = 0
                    var totalFrames = 0
                    var outputRate = 0
                    var writer: BookWavWriter? = null
                    var callbackFailure: String? = null
                    var lastReportMs = 0L
                    var stoppedByTarget = false
                    try {
                        for (part in parts) {
                            if (readerCancel || stoppedByTarget) break
                            val position = completedParts + 1
                            val chunkStart = SystemClock.elapsedRealtime()
                            _bookState.update { it.copy(
                                stage = "speech", status = "Синтез части " + position + "/" + parts.size
                            ) }
                            ChtecDiagnostics.record("STREAM_PART_BEGIN",
                                "n=" + position + " chars=" + part.length)
                            native.setProgressCallback { tokens, max ->
                                totalFrames = tokens
                                _bookState.update { it.copy(frames = tokens) }
                            }
                            val response = try {
                                native.synthesizeStreaming(
                                    text = part,
                                    speakerEmbeddingPath = voice.speakerEmbeddingPath,
                                    params = QwenEngine.NativeParams(languageId = 2069, maxAudioTokens = 160),
                                    chunkSeconds = 0.32f,
                                    leftContextSeconds = 0.16f,
                                    collectAudio = false,
                                    callback = QwenEngine.AudioChunkCallback { samples, rate, _, _, _, _, _, _, _, _ ->
                                        try {
                                            if (samples.isNotEmpty()) {
                                                if (writer == null) {
                                                    outputRate = rate
                                                    writer = BookWavWriter(readerProgress, outputRate)
                                                }
                                                require(outputRate == rate) { "WAV rate changed" }
                                                writer!!.append(samples) // checkpoint already saved to disk
                                                callbacks++
                                                val sec = writer!!.seconds
                                                val now = SystemClock.elapsedRealtime()
                                                if (callbacks == 1 || now-lastReportMs >= 5_000L) {
                                                    lastReportMs = now
                                                    ChtecDiagnostics.record("STREAM_AUDIO",
                                                        "callbacks=" + callbacks + " audio_s=" + sec +
                                                        " elapsed_ms=" + (now-started))
                                                }
                                                _bookState.update { it.copy(
                                                    wavReady = true, seconds = sec,
                                                    stage = "speech",
                                                    status = "Звук записывается: " +
                                                        "%.1f".format(java.util.Locale.US,sec) + " сек"
                                                ) }
                                            }
                                            if (writer != null && writer!!.seconds >= goal) stoppedByTarget = true
                                            !readerCancel && !stoppedByTarget
                                        } catch (ex: Exception) {
                                            callbackFailure = ex.message ?: ex.javaClass.simpleName
                                            ChtecDiagnostics.record("STREAM_IO_ERROR", callbackFailure ?: "unknown")
                                            false
                                        }
                                    }
                                )
                            } finally { native.setProgressCallback(null) }
                            val partElapsed = SystemClock.elapsedRealtime()-chunkStart
                            ChtecDiagnostics.record("STREAM_PART_END",
                                "n=" + position + " success=" + response.success +
                                " ms=" + partElapsed + " frames=" + totalFrames +
                                " error=" + response.errorMsg)
                            if (callbackFailure != null) error(callbackFailure!!)
                            if (!response.success && !readerCancel && !stoppedByTarget) {
                                error(response.errorMsg ?: "Qwen streaming failed")
                            }
                            completedParts++
                            val done = completedParts
                            _bookState.update { it.copy(chunksDone = done) }
                            if (readerCancel || stoppedByTarget) break
                        }
                    } finally { writer?.close() }
                    val playable = BookWavWriter.verifiedDuration(readerProgress)
                    if (playable != null && playable > 0.0) {
                        if (!readerCancel && callbackFailure == null) {
                            val complete = readerWav
                            if (complete.exists()) complete.delete()
                            if (!readerProgress.renameTo(complete)) {
                                ChtecDiagnostics.record("STREAM_MOVE", "using progress WAV")
                            }
                        }
                        Triple(playable, completedParts, readerCancel)
                    } else {
                        error("Не получен ни один аудиоблок Qwen: проверь журнал")
                    }
                }
            }
            readerTicker?.cancel()
            readerTicker = null
            _uiState.update { it.copy(busy = false) }
            result.fold(
                onSuccess = { (audioSeconds, completed, cancelled) ->
                    ChtecDiagnostics.record("STREAM_FINISH",
                        "audio_s=" + audioSeconds + " parts=" + completed + " cancelled=" + cancelled)
                    _bookState.update { it.copy(
                        busy = false, wavReady = true, chunksDone = completed,
                        seconds = audioSeconds, stage = "done", error = null,
                        status = if (cancelled) "Остановлено. Созданный WAV сохранён."
                        else "Готово " + "%.1f".format(java.util.Locale.US,audioSeconds) +
                            " сек. Можно сохранить WAV."
                    ) }
                },
                onFailure = { e ->
                    val partial = availableReaderWav()
                    ChtecDiagnostics.record("STREAM_FAILED",
                        "reason=" + (e.message ?: e.javaClass.simpleName) +
                        " partial=" + (partial != null))
                    _bookState.update { it.copy(
                        busy = false, wavReady = partial != null, stage = "error",
                        error = e.message ?: "Ошибка Qwen",
                        status = if (partial != null) "Ошибка; частичный WAV сохранён."
                                 else "Ошибка до первого аудиоблока."
                    ) }
                }
            )
        }
    }

"""
ui=ui[:start]+methods+ui[end:]

# Any valid checkpoint may be exported, even after crash/restart.
ui=only(ui,
    '        val output = readerWav\n        if (!output.isFile || output.length() < 44) {\n',
    '        val output = availableReaderWav()\n        if (output == null) {\n')

# Replace reader UI; keep original Studio, Voices and diagnostic screen untouched.
start=ui.find("@Composable\nprivate fun ReaderScreen(")
end=ui.find("@OptIn(ExperimentalMaterial3Api::class)\n@Composable\nprivate fun StudioScreen(",start)
assert start>=0 and end>start
screen=r"""@Composable
private fun ReaderScreen(viewModel: MainViewModel) {
    val state by viewModel.bookState.collectAsState()
    val tts by viewModel.uiState.collectAsState()
    val voices by viewModel.voices.collectAsState()
    val selected = voices.firstOrNull { it.voiceId == tts.selectedVoiceId }
    val open = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) viewModel.openReader(uri)
    }
    val save = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("audio/wav")) { uri ->
        if (uri != null) viewModel.exportReader(uri)
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Чтец — потоковая озвучка", style = MaterialTheme.typography.titleLarge)
        Text("PDF с текстовым слоем или TXT UTF-8. Голос: " +
             (selected?.name ?: "не выбран — открой Voices"))
        Button(onClick = {
            open.launch(arrayOf("application/pdf", "text/plain", "application/octet-stream"))
        }, enabled = !state.busy && !tts.busy) { Text("Открыть PDF / TXT") }
        Text("Извлечено символов: " + state.chars)
        if (state.preview.isNotBlank()) Text(state.preview.take(500),
            style = MaterialTheme.typography.bodySmall)
        Text("Рекомендуется начать с 15 секунд. После проверки — длинный тест.")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { viewModel.startReader(15) },
                enabled = state.documentReady && !state.busy && !tts.busy) {
                Text("Тест 15 секунд")
            }
            Button(onClick = { viewModel.startReader(300) },
                enabled = state.documentReady && !state.busy && !tts.busy) {
                Text("Тест 5 минут")
            }
        }
        OutlinedButton(onClick = viewModel::stopReader, enabled = state.busy) {
            Text("Остановить расчёт")
        }
        Text(state.status)
        Text("Этап: " + state.stage + "; частей: " + state.chunksDone + "/" + state.chunksTotal)
        Text("Прошло " + "%.1f".format(java.util.Locale.US,state.elapsedMs/1000.0) +
             " сек; звука " + "%.1f".format(java.util.Locale.US,state.seconds) +
             " сек; фреймов " + state.frames)
        if (state.rtf > 0.0) {
            Text("RTF " + "%.1f".format(java.util.Locale.US,state.rtf) +
                 " (меньше — быстрее)")
        }
        if (state.busy && state.seconds < 0.1) {
            Text("Если долго нет первого аудиоблока, открой вкладку Журнал. " +
                 "Кнопка «Остановить» сработает при очередном аудиоблоке.",
                style = MaterialTheme.typography.bodySmall)
        }
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(onClick = { save.launch("chtec_qwen_reading.wav") },
            enabled = state.wavReady) { Text("Сохранить WAV (включая частичный)") }
        Text("Приложение держать открытым. Для диагностики — вкладка «Журнал».",
             style = MaterialTheme.typography.bodySmall)
    }
}

"""
ui=ui[:start]+screen+ui[end:]

# Diagnostic panel should also show the streaming Reader timer and output.
ui=only(ui,
    '        Text("Чтец: " + book.status + ", фрагментов " + book.chunksDone + "/" + book.chunksTotal)\n',
    '        Text("Чтец: " + book.status + ", фрагментов " + book.chunksDone + "/" + book.chunksTotal +\n'
    '             ", фреймов " + book.frames + ", прошло " + book.elapsedMs/1000 + " сек")\n')
ui=only(ui,
    'Text("Кнопки прекращения вычислений Studio здесь нет: JNI не поддерживает безопасное прерывание. " +\n            "Во вкладке Чтец кнопка «Стоп» останавливает только между фрагментами.",\n',
    'Text("В Studio прерывание пока недоступно. Во вкладке Чтец потоковый JNI " +\n            "поддерживает отмену при поступлении очередного аудиоблока.",\n')

ui_path.write_text(ui,encoding="utf8")

dst=root/"app/src/main/java/com/qwen/tts/android/reader/BookWavWriter.kt"
shutil.copy2("qwen_integration/BookWavWriterCheckpoint.kt",dst)
test=root/"app/src/test/java/com/qwen/tts/android/reader/BookWavWriterTest.kt"
test.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2("qwen_integration/BookWavWriterTest.kt",test)

# Stable package name only within this experimental branch: existing diagnostic APK is NOT overwritten.
gradle=root/"app/build.gradle.kts"
g=gradle.read_text(encoding="utf8")
assert g.count('applicationId = "com.yagel.chtec.qwenreader.diag"') == 1
g=g.replace('applicationId = "com.yagel.chtec.qwenreader.diag"',
            'applicationId = "com.yagel.chtec.qwenreader.stream"')
gradle.write_text(g,encoding="utf8")
# Distinct launcher label and version so the test app cannot be confused with older installed builds.
strings_path = root/"app/src/main/res/values/strings.xml"
label = strings_path.read_text(encoding="utf8")
assert label.count("Чтец — Qwen (тест)") == 1
strings_path.write_text(label.replace("Чтец — Qwen (тест)", "Чтец — потоковый 0.2"), encoding="utf8")
g = gradle.read_text(encoding="utf8")
assert g.count('versionName = "0.1.0-chtec-test"') == 1
gradle.write_text(g.replace('versionName = "0.1.0-chtec-test"', 'versionName = "0.2.0-streaming"'), encoding="utf8")
print("STREAM_PATCH_OK: JNI streaming, cancel, checkpointed WAV, partial recovery, distinct app name")
