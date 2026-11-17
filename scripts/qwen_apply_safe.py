#!/usr/bin/env python3
"""Safe Qwen Reader fallback: use the ALREADY TESTED upstream synthesize() JNI,
not the unverified streaming JNI which returned null in Android log 2026-11-17.
Short segments, progress callback, checkpointed WAV, graceful stop between segments.
No C++ native changes. Strict anchors fail closed on drift.
"""
from pathlib import Path

root=Path("upstream")
p=root/"app/src/main/java/com/qwen/tts/android/MainActivity.kt"
q=root/"app/src/main/java/com/qwen/tts/studio/engine/QwenEngine.kt"
ui=p.read_text(encoding="utf8")
engine=q.read_text(encoding="utf8")

def once(old,new):
    global ui
    count=ui.count(old)
    if count!=1: raise SystemExit(f"SAFE_ABORT anchor={old[:90]!r} matched={count}")
    ui=ui.replace(old,new)

# Remove unused experimental bridge from QwenEngine; rely only on original synthesize JNI.
start=engine.find("    /**\n     * Uses native streaming symbol already present")
end=engine.find("    fun getLastError(): String? = nativeGetLastError(nativePtr)\n",start)
if start < 0 or end < 0 or end-start > 2600:
    raise SystemExit("SAFE_ABORT: cannot identify experimental engine method")
engine=engine[:start]+engine[end:]
start=engine.find("    private external fun nativeSynthesizeStreaming(\n")
end=engine.find("    private external fun nativeGetLastError(ptr: Long): String?\n",start)
if start<0 or end<0 or end-start>900:
    raise SystemExit("SAFE_ABORT: cannot identify experimental external method")
engine=engine[:start]+engine[end:]
assert "nativeSynthesizeStreaming" not in engine
q.write_text(engine,encoding="utf8")

start=ui.find("    fun startReader(targetAudioSeconds: Int = 15) {")
end=ui.find("    fun exportReader(uri: Uri) {",start)
if start<0 or end<0 or end-start>14000:
    raise SystemExit("SAFE_ABORT: cannot identify Reader synth function")

safe_method=r"""    fun startReader(targetAudioSeconds: Int = 15) {
        if (_bookState.value.busy || _uiState.value.busy) return
        if (readerText.length < 80) {
            _bookState.update { it.copy(error = "Нужен текст от 80 символов") }
            return
        }
        val voice = _uiState.value.selectedVoiceId?.let { id ->
            voices.value.firstOrNull { it.voiceId == id }
        }
        if (voice == null || !File(voice.speakerEmbeddingPath).isFile) {
            _bookState.update { it.copy(error = "Выбери созданный голос во вкладке Voices") }
            return
        }
        val variant = selectedVariant()
        if (!isModelReady(variant)) {
            _bookState.update { it.copy(error = "Модель не загружена. Открой Settings") }
            return
        }
        val goal = targetAudioSeconds.coerceIn(10, 300).toDouble()
        // ~one short sentence per native inference; the original Qwen Studio path is proven on device.
        val parts = BookChunker.split(readerText, 96)
        readerCancel = false
        readerProgress.delete()
        val started = SystemClock.elapsedRealtime()
        _bookState.update { it.copy(
            busy = true, error = null, wavReady = availableReaderWav() != null,
            chunksDone = 0, chunksTotal = parts.size, seconds = 0.0,
            elapsedMs = 0L, frames = 0, rtf = 0.0, stage = "load",
            status = "Подготовка локального синтеза; цель " + goal.toInt() + " сек звука",
        ) }
        ChtecDiagnostics.record("SAFE_START",
            "parts=" + parts.size + " target_audio_s=" + goal + " path=original_native")
        _uiState.update { it.copy(busy = true) }
        readerTicker?.cancel()
        readerTicker = viewModelScope.launch {
            var lastHeartbeat = 0L
            while (_bookState.value.busy) {
                kotlinx.coroutines.delay(1000L)
                val elapsed = SystemClock.elapsedRealtime() - started
                val generated = _bookState.value.seconds
                _bookState.update { it.copy(
                    elapsedMs = elapsed,
                    rtf = if (generated > 0.3) elapsed / 1000.0 / generated else 0.0,
                ) }
                if (elapsed - lastHeartbeat >= 10_000L) {
                    lastHeartbeat = elapsed
                    ChtecDiagnostics.record("SAFE_HEARTBEAT",
                        "stage=" + _bookState.value.stage +
                        " elapsed_ms=" + elapsed + " frames=" + _bookState.value.frames +
                        " audio_s=" + generated)
                    if (elapsed > 180_000L && _bookState.value.seconds == 0.0) {
                        _bookState.update { it.copy(
                            status = "За 3 минуты звук не появился. Нативная функция ещё занята. " +
                                "Остановка выполнится после текущей части."
                        ) }
                    }
                }
            }
        }
        viewModelScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    val native = ensureEngineLoaded(variant)
                    ChtecDiagnostics.record("SAFE_LOADED",
                        "elapsed_ms=" + (SystemClock.elapsedRealtime()-started))
                    var completed = 0
                    var outputRate = 0
                    var audioSeconds = 0.0
                    var writer: BookWavWriter? = null
                    try {
                        for (part in parts) {
                            if (readerCancel || audioSeconds >= goal) break
                            val position = completed + 1
                            val begin = SystemClock.elapsedRealtime()
                            _bookState.update { it.copy(stage = "speech", frames = 0,
                                status = "Синтез части " + position + "/" + parts.size) }
                            ChtecDiagnostics.record("SAFE_PART_BEGIN",
                                "n=" + position + " chars=" + part.length)
                            var frames = 0
                            val progressSupported = native.setProgressCallback { tokens, _ ->
                                frames = tokens
                                _bookState.update { it.copy(frames = tokens) }
                            }
                            if (!progressSupported) ChtecDiagnostics.record("SAFE_PROGRESS", "not available")
                            val response = try {
                                // Stable JNI call from the original Qwen Studio app:
                                native.synthesize(
                                    text = part,
                                    speakerEmbeddingPath = voice.speakerEmbeddingPath,
                                    params = QwenEngine.NativeParams(
                                        languageId = 2069, maxAudioTokens = 160
                                    ),
                                )
                            } finally {
                                native.setProgressCallback(null)
                            }
                            require(response.success) {
                                response.errorMsg ?: "Ошибка локального синтеза Qwen"
                            }
                            val samples = response.audio
                                ?: error("Qwen вернул результат без аудиоданных")
                            require(samples.isNotEmpty()) { "Qwen вернул пустое аудио" }
                            val rate = response.sampleRate.takeIf { it in 8_000..96_000 }
                                ?: error("Некорректная частота звука Qwen")
                            if (writer == null) {
                                outputRate = rate
                                writer = BookWavWriter(readerProgress, outputRate)
                            }
                            require(outputRate == rate) { "Частота WAV изменилась" }
                            writer.append(samples) // WAV remains valid on disk after every part
                            audioSeconds = writer.seconds
                            completed++
                            val count = completed
                            val sec = audioSeconds
                            val elapsed = SystemClock.elapsedRealtime()-begin
                            ChtecDiagnostics.record("SAFE_PART_END",
                                "n=" + count + " elapsed_ms=" + elapsed +
                                " audio_s=" + sec + " frames=" + frames +
                                " model_time_ms=" + response.timeMs)
                            _bookState.update { it.copy(
                                wavReady = true, chunksDone = count, seconds = sec,
                                status = "Сохранено " +
                                    "%.1f".format(java.util.Locale.US,sec) +
                                    " сек звука, фрагментов " + count,
                            ) }
                        }
                    } finally {
                        writer?.close()
                    }
                    val valid = BookWavWriter.verifiedDuration(readerProgress)
                        ?: error("Ни одного завершённого аудиофрагмента")
                    require(valid > 0.0) { "Пустая звуковая дорожка" }
                    if (!readerCancel) {
                        val target = readerWav
                        if (target.exists()) target.delete()
                        if (!readerProgress.renameTo(target)) {
                            ChtecDiagnostics.record("SAFE_MOVE", "WAV kept as partial file")
                        }
                    }
                    Triple(valid, completed, readerCancel)
                }
            }
            readerTicker?.cancel()
            readerTicker = null
            _uiState.update { it.copy(busy = false) }
            result.fold(onSuccess = { (duration, count, stopped) ->
                ChtecDiagnostics.record("SAFE_DONE",
                    "seconds=" + duration + " parts=" + count + " stopped=" + stopped)
                _bookState.update { it.copy(
                    busy = false, wavReady = true, chunksDone = count,
                    seconds = duration, stage = "done", error = null,
                    status = if (stopped) "Остановлено после фрагмента. WAV сохранён."
                        else "Готово " + "%.1f".format(java.util.Locale.US,duration) +
                            " сек звука. Можно экспортировать.",
                ) }
            }, onFailure = { error ->
                val partial = availableReaderWav()
                ChtecDiagnostics.record("SAFE_ERROR",
                    "reason=" + (error.message ?: error.javaClass.simpleName) +
                        " partial=" + (partial != null))
                _bookState.update { it.copy(
                    busy = false, wavReady = partial != null,
                    stage = "error", error = error.message ?: "Ошибка Qwen",
                    status = if (partial != null) "Сбой. Готовый фрагмент сохранён."
                             else "Сбой до первого WAV. Проверь вкладку Журнал.",
                ) }
            })
        }
    }

"""
ui=ui[:start]+safe_method+ui[end:]
once(
    "Запрошена остановка. Qwen прекратит расчёт при следующем аудиоблоке.",
    "Запрошена остановка. Текущий фрагмент должен завершиться."
)
once(
    'Text("Чтец — потоковая озвучка", style = MaterialTheme.typography.titleLarge)',
    'Text("Чтец — надёжная озвучка", style = MaterialTheme.typography.titleLarge)'
)
once(
    'Text("Рекомендуется начать с 15 секунд. После проверки — длинный тест.")',
    'Text("Сначала короткий тест. Отмена действует после текущего фрагмента.")'
)
once(
    'Text("Остановить расчёт")',
    'Text("Остановить после фрагмента")'
)
once(
    'Text("Если долго нет первого аудиоблока, открой вкладку Журнал. " +\n                 "Кнопка «Остановить» сработает при очередном аудиоблоке.",',
    'Text("Проверенный режим Qwen создаёт звук фрагментами. Если текущий фрагмент " +\n                 "рассчитывается долго, остановка сработает после его завершения.",'
)
once(
    'Text("В Studio прерывание пока недоступно. Во вкладке Чтец потоковый JNI " +\n            "поддерживает отмену при поступлении очередного аудиоблока.",',
    'Text("В Studio прерывание недоступно. В Чтеце остановка произойдёт после " +\n            "завершения текущего фрагмента.",'
)
ui_path=p
ui_path.write_text(ui,encoding="utf8")

gradle=root/"app/build.gradle.kts"
g=gradle.read_text(encoding="utf8")
assert g.count('applicationId = "com.yagel.chtec.qwenreader.stream"') == 1
g=g.replace('applicationId = "com.yagel.chtec.qwenreader.stream"',
            'applicationId = "com.yagel.chtec.qwenreader.safe"')
assert g.count('versionName = "0.2.0-streaming"') == 1
g=g.replace('versionName = "0.2.0-streaming"', 'versionName = "0.3.0-safe"')
gradle.write_text(g,encoding="utf8")
strings=root/"app/src/main/res/values/strings.xml"
label=strings.read_text(encoding="utf8")
assert label.count("Чтец — потоковый 0.2") == 1
strings.write_text(label.replace("Чтец — потоковый 0.2", "Чтец — надёжный 0.3"),
                   encoding="utf8")
assert "native.synthesizeStreaming" not in ui
assert "native.synthesize(" in ui
print("SAFE_PATCH_OK: original Qwen JNI, per-part WAV checkpoints, honest stop, diagnostics")
