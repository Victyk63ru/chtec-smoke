#!/usr/bin/env python3
"""Pinned upstream patch: Qwen Android -> isolated Chtec Reader prototype. No native-engine edits."""
from pathlib import Path
import shutil

root = Path("upstream")
ui_path = root / "app/src/main/java/com/qwen/tts/android/MainActivity.kt"
ui = ui_path.read_text(encoding="utf8")

def one(old, new):
    global ui
    n = ui.count(old)
    if n != 1:
        raise SystemExit("PATCH_ABORT: expected once, got %s: %r" % (n, old[:110]))
    ui = ui.replace(old, new)

one("import com.qwen.tts.android.data.VoiceRecorder\n",
"""import com.qwen.tts.android.data.VoiceRecorder
import com.qwen.tts.android.reader.BookTextReader
import com.qwen.tts.android.reader.BookChunker
import com.qwen.tts.android.reader.BookWavWriter
""")
one('val text: String = "Hello World from Qwen3 TTS running on Android on-device!",',
    'val text: String = "Привет! Это локальная озвучка книг в Чтеце.",')
one("    val selectedLanguageId: Int = 2050,\n",
    "    val selectedLanguageId: Int = 2069,\n")
one("class MainViewModel(application: Application) : AndroidViewModel(application) {",
"""data class BookUiState(
    val busy: Boolean = false,
    val documentReady: Boolean = false,
    val chars: Int = 0,
    val preview: String = "",
    val chunksDone: Int = 0,
    val chunksTotal: Int = 0,
    val seconds: Double = 0.0,
    val wavReady: Boolean = false,
    val status: String = "Открой PDF с текстовым слоем или TXT UTF-8",
    val error: String? = null
)

class MainViewModel(application: Application) : AndroidViewModel(application) {""")
one("    private val recorder = VoiceRecorder()\n",
"""    private val recorder = VoiceRecorder()
    private var readerText: String = ""
    @Volatile private var readerCancel = false
    private val readerWav: File get() = File(getApplication<Application>().filesDir, "reader/reader_test.wav")
    private val _bookState = MutableStateFlow(BookUiState())
    val bookState = _bookState.asStateFlow()
""")

methods = r"""
    fun openReader(uri: Uri) {
        if (_bookState.value.busy || _uiState.value.busy) return
        _bookState.update { it.copy(busy = true, error = null, wavReady = false, status = "Извлечение текста...") }
        viewModelScope.launch {
            runCatching { withContext(Dispatchers.IO) { BookTextReader.read(getApplication(), uri) } }
                .fold(onSuccess = { value ->
                    readerText = value
                    _bookState.update { it.copy(
                        busy = false, documentReady = true, chars = value.length,
                        preview = value.take(1000), chunksDone = 0, seconds = 0.0,
                        status = "Извлечено " + value.length + " символов", error = null,
                    ) }
                }, onFailure = { error ->
                    readerText = ""
                    _bookState.update { it.copy(
                        busy = false, documentReady = false, preview = "",
                        error = error.message ?: "Не прочитать файл", status = "Ошибка чтения",
                    ) }
                })
        }
    }

    fun stopReader() {
        if (_bookState.value.busy) {
            readerCancel = true
            _bookState.update { it.copy(status = "Остановка после текущего фрагмента...") }
        }
    }

    fun startReader() {
        if (_bookState.value.busy || _uiState.value.busy) return
        if (readerText.length < 1000) {
            _bookState.update { it.copy(error = "Для длинного теста нужен текст от 1000 символов") }
            return
        }
        val voice = _uiState.value.selectedVoiceId?.let { id ->
            voices.value.firstOrNull { it.voiceId == id }
        }
        if (voice == null) {
            _bookState.update { it.copy(error = "Выбери свой голос во вкладке Voices") }
            return
        }
        val variant = selectedVariant()
        if (!isModelReady(variant)) {
            _bookState.update { it.copy(error = "Модель не загружена. Открой Settings.") }
            return
        }
        val parts = BookChunker.split(readerText)
        readerCancel = false
        _bookState.update { it.copy(
            busy = true, error = null, wavReady = false, chunksDone = 0,
            chunksTotal = parts.size, seconds = 0.0, status = "Озвучка до 300 секунд",
        ) }
        _uiState.update { it.copy(busy = true) }
        viewModelScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    val native = ensureEngineLoaded(variant)
                    val tmp = File(getApplication<Application>().filesDir, "reader/reader_test.part")
                    tmp.parentFile?.mkdirs()
                    tmp.delete()
                    var writer: BookWavWriter? = null
                    var rate = 0
                    var done = 0
                    var seconds = 0.0
                    try {
                        for (part in parts) {
                            if (readerCancel) error("Остановлено пользователем")
                            val audio = native.synthesize(
                                text = part,
                                speakerEmbeddingPath = voice.speakerEmbeddingPath,
                                params = QwenEngine.NativeParams(languageId = 2069),
                            )
                            require(audio.success && audio.audio != null && audio.audio.isNotEmpty()) {
                                audio.errorMsg ?: "Qwen не создал аудио"
                            }
                            val sr = audio.sampleRate.takeIf { it > 0 } ?: 24_000
                            if (writer == null) {
                                writer = BookWavWriter(tmp, sr)
                                rate = sr
                            }
                            require(sr == rate) { "Частота WAV изменилась" }
                            writer.append(audio.audio)
                            seconds = writer.seconds
                            done++
                            val count = done
                            val duration = seconds
                            _bookState.update { it.copy(
                                chunksDone = count, seconds = duration,
                                status = "Часть " + count + "/" + parts.size +
                                    ", звук " + "%.1f".format(java.util.Locale.US, duration) + " сек",
                            ) }
                            if (seconds >= 300.0) break
                        }
                    } finally { writer?.close() }
                    if (readerCancel) {
                        tmp.delete()
                        error("Остановлено пользователем")
                    }
                    require(done > 0 && tmp.isFile && tmp.length() > 44) { "Нет готового WAV" }
                    val target = readerWav
                    if (target.exists()) require(target.delete()) { "Нельзя заменить старый WAV" }
                    require(tmp.renameTo(target)) { "Ошибка сохранения WAV" }
                    Pair(seconds, done)
                }
            }
            _uiState.update { it.copy(busy = false) }
            result.fold(onSuccess = { (duration, count) ->
                _bookState.update { it.copy(
                    busy = false, wavReady = true, seconds = duration, chunksDone = count,
                    status = if (duration >= 300.0) "Готов WAV на 5 минут"
                        else "Текст закончился на " + "%.1f".format(java.util.Locale.US, duration) +
                             " сек. Для полного теста нужен более длинный PDF.",
                ) }
            }, onFailure = { error ->
                _bookState.update { it.copy(
                    busy = false, wavReady = false,
                    status = "Ошибка синтеза", error = error.message ?: "Неизвестная ошибка",
                ) }
            })
        }
    }

    fun exportReader(uri: Uri) {
        val output = readerWav
        if (!output.isFile || output.length() < 44) {
            _bookState.update { it.copy(error = "Нет WAV для сохранения") }
            return
        }
        viewModelScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    getApplication<Application>().contentResolver.openOutputStream(uri)?.use { dst ->
                        output.inputStream().use { it.copyTo(dst) }
                    } ?: error("Нельзя сохранить по выбранному адресу")
                }
            }.fold(
                onSuccess = { _bookState.update { it.copy(status = "WAV экспортирован", error = null) } },
                onFailure = { e -> _bookState.update { it.copy(error = e.message ?: "Ошибка экспорта") } },
            )
        }
    }

"""
one("    fun updateText(value: String) {\n", methods + "    fun updateText(value: String) {\n")
one('    object Studio : AppDestination("studio", "Studio", { Icon(Icons.AutoMirrored.Filled.VolumeUp, contentDescription = null) })\n',
    '    object Studio : AppDestination("studio", "Studio", { Icon(Icons.AutoMirrored.Filled.VolumeUp, contentDescription = null) })\n'
    '    object Reader : AppDestination("reader", "Чтец", { Icon(Icons.Default.GraphicEq, contentDescription = null) })\n')
one("    AppDestination.Studio,\n    AppDestination.Voices,\n",
    "    AppDestination.Studio,\n    AppDestination.Reader,\n    AppDestination.Voices,\n")
one("            composable(AppDestination.Studio.route) {\n                StudioScreen(viewModel)\n            }\n",
    "            composable(AppDestination.Studio.route) {\n                StudioScreen(viewModel)\n            }\n"
    "            composable(AppDestination.Reader.route) {\n                ReaderScreen(viewModel)\n            }\n")
screen = r"""
@Composable
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
        Text("Чтец — испытание длинной озвучки", style = MaterialTheme.typography.titleLarge)
        Text("PDF с текстом или TXT UTF-8. Без облачных API после загрузки модели.")
        Button(onClick = { open.launch(arrayOf("application/pdf", "text/plain", "application/octet-stream")) },
            enabled = !state.busy && !tts.busy) { Text("Открыть PDF / TXT") }
        Text("Текст: " + state.chars + " символов")
        if (state.preview.isNotBlank()) {
            Text("Проверка текста:", fontWeight = FontWeight.SemiBold)
            Text(state.preview, style = MaterialTheme.typography.bodySmall)
        }
        Text("Голос: " + (selected?.name ?: "не выбран — открой Voices"))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = viewModel::startReader,
                enabled = state.documentReady && !state.busy && !tts.busy) {
                Text("Тест до 5 минут")
            }
            OutlinedButton(onClick = viewModel::stopReader, enabled = state.busy) {
                Text("Стоп")
            }
        }
        Text(state.status)
        if (state.chunksTotal > 0) {
            Text("Части: " + state.chunksDone + "/" + state.chunksTotal +
                ", звук: " + "%.1f".format(java.util.Locale.US, state.seconds) + " сек")
        }
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Button(onClick = { save.launch("chtec_qwen_reader_5min.wav") },
            enabled = state.wavReady && !state.busy) { Text("Сохранить WAV") }
        Text("Это тест. Держи приложение открытым: фоновая служба ещё не реализована.",
            style = MaterialTheme.typography.bodySmall)
    }
}

"""
one("@OptIn(ExperimentalMaterial3Api::class)\n@Composable\nprivate fun StudioScreen(viewModel: MainViewModel) {",
    screen + "@OptIn(ExperimentalMaterial3Api::class)\n@Composable\nprivate fun StudioScreen(viewModel: MainViewModel) {")
ui_path.write_text(ui, encoding="utf8")
gradle = root/"app/build.gradle.kts"
s = gradle.read_text(encoding="utf8")
for old, new in [
    ('applicationId = "com.qwen.tts.android"', 'applicationId = "com.yagel.chtec.qwenreader"'),
    ('versionName = "0.1.0"', 'versionName = "0.1.0-chtec-test"'),
    ('    implementation(libs.androidx.core.ktx)',
     '    implementation("com.tom-roush:pdfbox-android:2.0.27.0")\n'
     '    testImplementation("junit:junit:4.13.2")\n'
     '    implementation(libs.androidx.core.ktx)')
]:
    if s.count(old) != 1:
        raise SystemExit("GRADLE_PATCH_ABORT " + old)
    s = s.replace(old, new)
gradle.write_text(s, encoding="utf8")
strings = root/"app/src/main/res/values/strings.xml"
text = strings.read_text(encoding="utf8")
assert text.count("Qwen3 TTS") == 1
strings.write_text(text.replace("Qwen3 TTS", "Чтец — Qwen (тест)"), encoding="utf8")
for name in ("BookChunker.kt", "BookTextReader.kt", "BookWavWriter.kt"):
    dst = root/"app/src/main/java/com/qwen/tts/android/reader"/name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path("qwen_integration")/name, dst)
test = root/"app/src/test/java/com/qwen/tts/android/reader/BookChunkerTest.kt"
test.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2("qwen_integration/BookChunkerTest.kt", test)
print("PATCH_OK: Qwen core untouched; Reader and tests added")
