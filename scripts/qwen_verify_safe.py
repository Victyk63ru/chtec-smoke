from pathlib import Path
root=Path("upstream")
q=(root/"app/src/main/java/com/qwen/tts/studio/engine/QwenEngine.kt").read_text()
ui=(root/"app/src/main/java/com/qwen/tts/android/MainActivity.kt").read_text()
g=(root/"app/build.gradle.kts").read_text()
for c in [
 "native.synthesize(\n", "SAFE_START", "SAFE_PART_BEGIN",
 "SAFE_PART_END", "BookWavWriter.verifiedDuration(readerProgress)",
 "writer.append(samples)", "native.setProgressCallback(null)",
 "fun stopReader()", "fun exportReader(uri: Uri)"
]:
 assert c in ui,c
assert "native.synthesizeStreaming" not in ui
assert "nativeSynthesizeStreaming" not in q
assert 'applicationId = "com.yagel.chtec.qwenreader.safe"' in g
assert 'versionName = "0.3.0-safe"' in g
print("SAFE_STATIC_OK: Reader calls original Qwen JNI; checkpoints and diagnostics present")
