package com.openmoss.ttsnano.onnxruntime

import android.app.Activity
import android.content.Intent
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.media.MediaPlayer
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.io.File

/**
 * Stage A Android smoke test: download once, synthesize WAV offline with the
 * upstream built-in Junhao voice. This is NOT personal-voice cloning yet.
 *
 * The diagnostic log can be copied without ADB or a PC.
 */
class MainActivity : Activity() {
    private val mainHandler = Handler(Looper.getMainLooper())
    private lateinit var logView: TextView
    private lateinit var input: EditText
    private lateinit var downloadButton: Button
    private lateinit var synthButton: Button
    private lateinit var replayButton: Button
    private var player: MediaPlayer? = null
    private var lastAudio: File? = null
    private var selectedVoiceWav: File? = null
    private lateinit var chooseVoiceButton: Button
    private var busy = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "Чтец — тест MOSS v0.4"
        input = EditText(this).apply {
            hint = "Введите короткую фразу на русском"
            setText("Привет! Проверяем русский голос в автономном режиме.")
            minLines = 2
        }
        chooseVoiceButton = Button(this).apply {
            text = "Выбрать мой голос (WAV до 12 сек)"
            setOnClickListener {
                if (busy) return@setOnClickListener
                val chooser = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "*/*"
                    putExtra(Intent.EXTRA_MIME_TYPES, arrayOf(
                        "audio/wav", "audio/x-wav", "audio/wave", "application/octet-stream"
                    ))
                }
                startActivityForResult(chooser, 1234)
            }
        }
        downloadButton = Button(this).apply {
            text = "1. Скачать и проверить модели"
            setOnClickListener { runTask(downloadOnly = true) }
        }
        synthButton = Button(this).apply {
            text = "2. Создать WAV (можно в авиарежиме)"
            setOnClickListener { runTask(downloadOnly = false) }
        }
        replayButton = Button(this).apply {
            text = "Прослушать последний WAV"
            isEnabled = false
            setOnClickListener {
                val file = lastAudio
                if (file?.isFile == true) play(file)
                else report("WAV не найден — выполните синтез заново")
            }
        }
        logView = TextView(this).apply {
            textSize = 13f
            setTextIsSelectable(true)
        }
        val copyButton = Button(this).apply {
            text = "Скопировать журнал ошибок"
            setOnClickListener {
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("Чтец — журнал", logView.text.toString()))
                Toast.makeText(this@MainActivity, "Журнал скопирован", Toast.LENGTH_SHORT).show()
            }
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
            addView(input)
            addView(chooseVoiceButton)
            addView(downloadButton)
            addView(synthButton)
            addView(replayButton)
            addView(copyButton)
            addView(logView)
        }
        setContentView(ScrollView(this).apply {
            addView(content, ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ))
        })
        report("Первый запуск: загрузите модели через интернет (~760 МБ).")
        report("Затем включите авиарежим и нажмите «Создать WAV».")
        report("Если WAV не выбран — используется встроенный тестовый голос.")
        report("После выбора WAV создаётся временный профиль только на телефоне.")
    }

    private fun report(message: String) = mainHandler.post { logView.append("$message\n") }

    private fun setBusy(value: Boolean) {
        busy = value
        downloadButton.isEnabled = !value
        chooseVoiceButton.isEnabled = !value
        synthButton.isEnabled = !value
        if (value) replayButton.isEnabled = false
        else replayButton.isEnabled = lastAudio?.isFile == true
    }

    private fun runTask(downloadOnly: Boolean) {
        if (busy) return
        val text = input.text.toString().trim()
        if (!downloadOnly && text.isBlank()) {
            report("Ошибка: сначала введите текст")
            return
        }
        setBusy(true)
        logView.text = ""
        Thread {
            try {
                val root = File(filesDir, "moss_tts_onnx")
                report("Проверяю модели...")
                ModelManager.ensureModels(root) { report(it) }
                report("Все файлы моделей прошли имеющиеся проверки")
                if (downloadOnly) {
                    report("Загрузка закончена. Для проверки автономности включите авиарежим.")
                    return@Thread
                }
                val tokenizer = SentencePieceTokenizer(File(
                    root, "MOSS-TTS-Nano-100M-ONNX/tokenizer.model"
                ))
                val tokens = tokenizer.encode(text)
                require(tokens.isNotEmpty()) { "Токенизатор вернул пустой результат" }
                report("Токенов: ${tokens.size}. Создаю WAV...")
                val voiceCodes = selectedVoiceWav?.let { wav ->
                    report("Кодирую локальный образец голоса...")
                    VoiceProfileEncoder.encode(root, wav).also { codes ->
                        report("Профиль голоса: ${codes.size} аудиофреймов")
                    }
                }
                val startedAt = System.currentTimeMillis()
                val output = File(cacheDir, "chtec_smoke.wav")
                MossOnnxDemoEngine(root, cacheDir, cpuThreads = 2).use { engine ->
                    val result = engine.synthesize(
                        tokens, output, voice = "Junhao",
                        promptAudioCodes = voiceCodes, maxFrames = 160
                    )
                    report("WAV: ${result.durationMs} мс, генерация ${result.elapsedMs} мс")
                }
                require(output.isFile && output.length() > 44) { "Файл WAV пуст или отсутствует" }
                report("Файл: ${output.absolutePath}")
                report("Размер: ${output.length()} байт, всего ${System.currentTimeMillis() - startedAt} мс")
                mainHandler.post {
                    lastAudio = output
                    play(output)
                }
            } catch (error: Throwable) {
                android.util.Log.e("ChtecSmoke", "Stage A failed", error)
                report("ОШИБКА ${error.javaClass.simpleName}: ${error.message}")
                report("Нажмите «Скопировать журнал ошибок» и пришлите текст.")
            } finally {
                mainHandler.post { setBusy(false) }
            }
        }.start()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 1234 || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        try {
            val target = File(filesDir, "personal_reference.wav")
            val tmp = File(filesDir, "personal_reference.wav.part")
            contentResolver.openInputStream(uri)?.use { inputStream ->
                tmp.outputStream().use { output -> inputStream.copyTo(output) }
            } ?: error("Не удалось открыть выбранный файл")
            VoiceReferenceWav.read(tmp) // validate BEFORE replacing the existing sample
            if (target.exists()) target.delete()
            require(tmp.renameTo(target)) { "Не удалось сохранить WAV внутри приложения" }
            selectedVoiceWav = target
            report("Личный образец выбран и сохранён локально, ${target.length()} байт.")
        } catch (error: Exception) {
            report("Ошибка импорта голоса: ${error.message}")
        }
    }

    private fun play(file: File) {
        try {
            player?.release()
            player = MediaPlayer().apply {
                setDataSource(file.absolutePath)
                prepare()
                start()
            }
        } catch (error: Exception) {
            report("Не удалось воспроизвести WAV: ${error.message}")
        }
    }

    override fun onDestroy() {
        player?.release()
        player = null
        super.onDestroy()
    }
}
