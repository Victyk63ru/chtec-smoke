#!/usr/bin/env python3
"""Fix Kotlin/JNI ABI mismatch for the PINNED native Qwen commit 4562731...:
C++ streaming function does NOT accept icl_prompt_path. The earlier Kotlin
declaration inserted it, shifting params and making callback pointer null.
Provide a safe fallback to the original non-streaming JNI if JNI still returns null.
"""
from pathlib import Path
p=Path("upstream/app/src/main/java/com/qwen/tts/studio/engine/QwenEngine.kt")
s=p.read_text(encoding="utf8")

def one(old,new):
    global s
    n=s.count(old)
    if n!=1: raise SystemExit(f"ABI_PATCH_ABORT: found {n} for {old[:120]!r}")
    s=s.replace(old,new)

one("package com.qwen.tts.studio.engine\n",
    "package com.qwen.tts.studio.engine\n\nimport com.qwen.tts.android.reader.ChtecDiagnostics\n")

old="""    ): NativeResult = nativeSynthesizeStreaming(
        nativePtr, text, null, speakerEmbeddingPath, null,
        params, chunkSeconds, leftContextSeconds, collectAudio, callback,
    )
"""
new="""    ): NativeResult {
        // The pinned C++ JNI accepts exactly three jstrings (text, reference, speaker).
        // It does NOT accept iclPromptPath; earlier Kotlin passed an extra null.
        var callbackProducedAudio = false
        val monitoredCallback = AudioChunkCallback {
            samples, sampleRate, startSample, endSample, startFrame, endFrame,
            startTextByte, endTextByte, textAlignmentKind, confidence ->
            callbackProducedAudio = true
            callback.onAudioChunk(
                samples, sampleRate, startSample, endSample, startFrame, endFrame,
                startTextByte, endTextByte, textAlignmentKind, confidence,
            )
        }
        val result: NativeResult? = try {
            nativeSynthesizeStreaming(
                nativePtr, text, null, speakerEmbeddingPath,
                params, chunkSeconds, leftContextSeconds, collectAudio, monitoredCallback,
            )
        } catch (error: LinkageError) {
            ChtecDiagnostics.record("STREAM_JNI_ERROR", error.message ?: error.javaClass.simpleName)
            null
        }
        if (result != null) return result

        // Don't repeat synthesis if any audio was emitted: duplicate speech is worse.
        if (callbackProducedAudio) {
            return NativeResult(null, 0, false, "JNI returned null after writing audio; see partial WAV", 0)
        }
        ChtecDiagnostics.record("STREAM_JNI_FALLBACK",
            "native returned null before first audio, using original Qwen synthesis")
        val stable: NativeResult? =
            nativeSynthesize(nativePtr, text, null, speakerEmbeddingPath, params)
        if (stable == null) {
            return NativeResult(null, 0, false, "Both native synthesis methods returned null", 0)
        }
        val audio = stable.audio
        if (stable.success && audio != null && audio.isNotEmpty()) {
            callback.onAudioChunk(
                audio, stable.sampleRate, 0L, audio.size.toLong(), 0, 0,
                0, text.toByteArray(Charsets.UTF_8).size, 0, 0f,
            )
        }
        return stable
    }
"""
one(old,new)
one("""        iclPromptPath: String?,
        params: NativeParams,
        chunkSeconds: Float,
""","""        params: NativeParams,
        chunkSeconds: Float,
""")
one("""        callback: AudioChunkCallback,
    ): NativeResult
""","""        callback: AudioChunkCallback,
    ): NativeResult?
""")
p.write_text(s,encoding="utf8")

ui_path=Path("upstream/app/src/main/java/com/qwen/tts/android/MainActivity.kt")
ui=ui_path.read_text(encoding="utf8")
# Only display label and package need changing; Reader uses the ABI-fixed
# synthesizeStreaming wrapper, with per-audio-block WAV checkpoint already in v0.2.
assert 'native.synthesizeStreaming(' in ui
ui_path.write_text(ui,encoding="utf8")

gpath=Path("upstream/app/build.gradle.kts")
g=gpath.read_text(encoding="utf8")
assert g.count('applicationId = "com.yagel.chtec.qwenreader.stream"')==1
g=g.replace('applicationId = "com.yagel.chtec.qwenreader.stream"',
            'applicationId = "com.yagel.chtec.qwenreader.fixed"')
assert g.count('versionName = "0.2.0-streaming"')==1
g=g.replace('versionName = "0.2.0-streaming"', 'versionName = "0.3.0-jni-fixed"')
gpath.write_text(g,encoding="utf8")
lpath=Path("upstream/app/src/main/res/values/strings.xml")
label=lpath.read_text(encoding="utf8")
assert label.count("Чтец — потоковый 0.2")==1
lpath.write_text(label.replace("Чтец — потоковый 0.2", "Чтец — исправленный 0.3"),
                 encoding="utf8")
print("ABI_FIXED: pinned C++/Kotlin JNI alignment; safe fallback when native null")
