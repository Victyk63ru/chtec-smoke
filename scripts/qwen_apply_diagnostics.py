#!/usr/bin/env python3
"""Add user-visible local diagnostics AFTER pinned Qwen Reader patch; strict anchors."""
from pathlib import Path
import shutil

p=Path("upstream/app/src/main/java/com/qwen/tts/android/MainActivity.kt")
s=p.read_text(encoding="utf8")
def once(old,new):
    global s
    n=s.count(old)
    if n!=1: raise SystemExit(f"DIAG_PATCH_ABORT found {n}: {old[:120]!r}")
    s=s.replace(old,new)

once("import android.Manifest\n",
"""import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
""")
once("import com.qwen.tts.android.reader.BookWavWriter\n",
"""import com.qwen.tts.android.reader.BookWavWriter
import com.qwen.tts.android.reader.ChtecDiagnostics
""")
once('    object Reader : AppDestination("reader", "Чтец", { Icon(Icons.Default.GraphicEq, contentDescription = null) })\n',
     '    object Reader : AppDestination("reader", "Чтец", { Icon(Icons.Default.GraphicEq, contentDescription = null) })\n'
     '    object Diagnostics : AppDestination("diagnostics", "Журнал", { Icon(Icons.Default.History, contentDescription = null) })\n')
once("    AppDestination.Reader,\n    AppDestination.Voices,\n",
     "    AppDestination.Reader,\n    AppDestination.Diagnostics,\n    AppDestination.Voices,\n")
once('            composable(AppDestination.Reader.route) {\n                ReaderScreen(viewModel)\n            }\n',
     '            composable(AppDestination.Reader.route) {\n                ReaderScreen(viewModel)\n            }\n'
     '            composable(AppDestination.Diagnostics.route) {\n                DiagnosticsScreen(viewModel)\n            }\n')
once('        super.onCreate(savedInstanceState)\n        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)\n',
     '        super.onCreate(savedInstanceState)\n        ChtecDiagnostics.initialize(applicationContext)\n        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)\n')
# Honest stop behavior: in Reader, only between fragments. Studio/native Qwen has no safe interrupt.
once('        _bookState.update { it.copy(busy = true, error = null, wavReady = false, status = "Извлечение текста...") }\n',
     '        ChtecDiagnostics.record("READER_IMPORT", "start")\n'
     '        _bookState.update { it.copy(busy = true, error = null, wavReady = false, status = "Извлечение текста...") }\n')
once('                    readerText = value\n',
     '                    ChtecDiagnostics.record("READER_IMPORT", "complete chars=" + value.length)\n'
     '                    readerText = value\n')
once('                    readerText = ""\n',
     '                    ChtecDiagnostics.record("READER_IMPORT", "failed reason=" + error.message)\n'
     '                    readerText = ""\n')
once('            readerCancel = true\n',
     '            ChtecDiagnostics.record("READER_STOP", "requested; will stop after the current native chunk")\n'
     '            readerCancel = true\n')
once('        val parts = BookChunker.split(readerText)\n',
     '        val parts = BookChunker.split(readerText)\n'
     '        ChtecDiagnostics.record("READER_START", "chars=" + readerText.length + " parts=" + parts.size)\n')
once('                            done++\n                            val count = done\n',
     '                            done++\n'
     '                            ChtecDiagnostics.record("READER_PROGRESS", "parts=" + done + " seconds=" + seconds)\n'
     '                            val count = done\n')
once('            result.fold(onSuccess = { (duration, count) ->\n',
     '            result.fold(onSuccess = { (duration, count) ->\n'
     '                ChtecDiagnostics.record("READER_OK", "seconds=" + duration + " parts=" + count)\n')
once('            }, onFailure = { error ->\n                _bookState.update { it.copy(\n',
     '            }, onFailure = { error ->\n'
     '                ChtecDiagnostics.record("READER_ERROR", error.message ?: error.javaClass.simpleName)\n'
     '                _bookState.update { it.copy(\n')
# Original Qwen Studio logs (without book text or user voice filename)
once('    fun synthesize() {\n        val text = _uiState.value.text.trim()\n',
     '    fun synthesize() {\n        val text = _uiState.value.text.trim()\n'
     '        ChtecDiagnostics.record("STUDIO_START", "chars=" + text.length + " lang=" + _uiState.value.selectedLanguageId)\n')
once('                    generatedAudio = nativeResult.audio\n',
     '                    ChtecDiagnostics.record("STUDIO_OK", "duration_ms=" + nativeResult.timeMs + " samples=" + nativeResult.audio.size)\n'
     '                    generatedAudio = nativeResult.audio\n')
once('                            status = "Synthesis failed",\n                            error = nativeResult.errorMsg ?: "Native synthesis failed",\n',
     '                            status = "Synthesis failed",\n                            error = nativeResult.errorMsg ?: "Native synthesis failed",\n')
# The above replacement is intentionally a no-op: error-log insertion below uses an unambiguous anchor.
once('                    if (!nativeResult.success || nativeResult.audio == null) {\n',
     '                    if (!nativeResult.success || nativeResult.audio == null) {\n'
     '                        ChtecDiagnostics.record("STUDIO_ERROR", nativeResult.errorMsg ?: "Native synthesis failed")\n')
once('                onFailure = { throwable ->\n                    stopBusyTicker()\n                    _uiState.update {\n                        it.copy(\n                            busy = false,\n                            status = "Synthesis failed",\n',
     '                onFailure = { throwable ->\n'
     '                    ChtecDiagnostics.record("STUDIO_EXCEPTION", throwable.message ?: throwable.javaClass.simpleName)\n'
     '                    stopBusyTicker()\n'
     '                    _uiState.update {\n                        it.copy(\n                            busy = false,\n                            status = "Synthesis failed",\n')
# Persistent heartbeat from the existing 250ms UI ticker even while Qwen JNI occupies its worker thread.
once('        operationTickerJob = viewModelScope.launch {\n            while (true) {\n',
     '        ChtecDiagnostics.record("OP_START", status)\n'
     '        operationTickerJob = viewModelScope.launch {\n'
     '            var lastDiagMs = 0L\n'
     '            while (true) {\n')
once('                val elapsed = SystemClock.elapsedRealtime() - start\n',
     '                val elapsed = SystemClock.elapsedRealtime() - start\n'
     '                if (elapsed - lastDiagMs >= 10_000L) {\n'
     '                    lastDiagMs = elapsed\n'
     '                    ChtecDiagnostics.record("HEARTBEAT", "elapsed_ms=" + elapsed + " frames=" + _uiState.value.synthesisFrames + " status=" + _uiState.value.status)\n'
     '                }\n')
screen = r"""
@Composable
private fun DiagnosticsScreen(viewModel: MainViewModel) {
    val context = LocalContext.current
    val state by viewModel.uiState.collectAsState()
    val book by viewModel.bookState.collectAsState()
    var log by remember { mutableStateOf(ChtecDiagnostics.snapshot()) }
    val saveLog = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/plain")) { uri ->
        if (uri != null) {
            try {
                val data = ChtecDiagnostics.snapshot().toByteArray(Charsets.UTF_8)
                context.contentResolver.openOutputStream(uri)?.use { it.write(data) }
                    ?: error("Невозможно открыть выбранный путь")
                log = ChtecDiagnostics.snapshot()
            } catch (error: Exception) {
                ChtecDiagnostics.record("EXPORT_ERROR", error.message ?: "Неизвестно")
                log = ChtecDiagnostics.snapshot()
            }
        }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Журнал Чтеца", style = MaterialTheme.typography.titleLarge)
        Text("Studio: " + state.status + ", время " +
            "%.1f".format(java.util.Locale.US, state.operationElapsedMillis / 1000.0) +
            " сек, аудиофреймов " + state.synthesisFrames)
        Text("Чтец: " + book.status + ", фрагментов " + book.chunksDone + "/" + book.chunksTotal)
        Text("Кнопки прекращения вычислений Studio здесь нет: JNI не поддерживает безопасное прерывание. " +
            "Во вкладке Чтец кнопка «Стоп» останавливает только между фрагментами.",
            style = MaterialTheme.typography.bodySmall)
        Button(onClick = { log = ChtecDiagnostics.snapshot() }) { Text("Обновить журнал") }
        Button(onClick = {
            val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("Чтец — журнал", ChtecDiagnostics.snapshot()))
            log = ChtecDiagnostics.snapshot()
        }) { Text("Скопировать журнал") }
        Button(onClick = { saveLog.launch("chtec_diagnostics.txt") }) { Text("Сохранить отчёт TXT") }
        Text(log.takeLast(16_000), style = MaterialTheme.typography.bodySmall)
    }
}

"""
once("@Composable\nprivate fun ReaderScreen(viewModel: MainViewModel) {",
     screen + "@Composable\nprivate fun ReaderScreen(viewModel: MainViewModel) {")
p.write_text(s,encoding="utf8")
target=Path("upstream/app/src/main/java/com/qwen/tts/android/reader/ChtecDiagnostics.kt")
target.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2("qwen_integration/ChtecDiagnostics.kt",target)
print("DIAGNOSTICS_PATCH_OK",len(s))

# Side-by-side diagnostic build; leave installed reader and voice files untouched.
gradle = Path("upstream/app/build.gradle.kts")
content = gradle.read_text(encoding="utf8")
assert content.count('applicationId = "com.yagel.chtec.qwenreader"') == 1
content = content.replace('applicationId = "com.yagel.chtec.qwenreader"', 'applicationId = "com.yagel.chtec.qwenreader.diag"')
gradle.write_text(content, encoding="utf8")
