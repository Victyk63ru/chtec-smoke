#!/usr/bin/env python3
"""Independent sanity check of the ACTUAL checked-out pinned C++ JNI signature."""
from pathlib import Path
import re
base=Path("upstream")
cpp=(base/"external/qwen3-tts.cpp/src/qwen3_tts_jni.cpp").read_text(encoding="utf8")
kt=(base/"app/src/main/java/com/qwen/tts/studio/engine/QwenEngine.kt").read_text(encoding="utf8")
ui=(base/"app/src/main/java/com/qwen/tts/android/MainActivity.kt").read_text(encoding="utf8")
native=re.search(
    r"JNIEXPORT jobject JNICALL Java_com_qwen_tts_studio_engine_QwenEngine_nativeSynthesizeStreaming\s*\((.*?)\)\s*\{",
    cpp,re.S)
assert native,"missing JNI streaming export"
native_types=[]
for a in native.group(1).split(","):
    a=a.strip()
    m=re.match(r"(JNIEnv\s*\*|jobject|jlong|jstring|jfloat|jboolean)\s+\w+$",a)
    assert m, f"Unparsed JNI parameter: {a}"
    native_types.append(m.group(1).replace(" ",""))
expected_cpp=["JNIEnv*","jobject","jlong","jstring","jstring","jstring",
              "jobject","jfloat","jfloat","jboolean","jobject"]
assert native_types==expected_cpp,f"Native ABI mismatch: {native_types!r}"
method=re.search(r"private external fun nativeSynthesizeStreaming\s*\((.*?)\)\s*:\s*NativeResult\?",kt,re.S)
assert method,"native Kotlin method missing"
kotlin_args=re.findall(r"(\w+):\s*(\w+\??)",method.group(1))
                  )
assert kotlin_args==[
 ('ptr','Long'),('text','String'),('referenceWav','String?'),
 ('speakerEmbeddingPath','String?'),('params','NativeParams'),
 ('chunkSeconds','Float'),('leftContextSeconds','Float'),
 ('collectAudio','Boolean'),('callback','AudioChunkCallback')
],f"Kotlin ABI mismatch: {kotlin_args!r}"
assert 'nativePtr, text, null, speakerEmbeddingPath,\n                params,' in kt
assert 'iclPromptPath:' not in method.group(1)
assert 'STREAM_JNI_FALLBACK' in kt
assert '"([FIJJIIIIIF)Z"' in cpp
assert "native.synthesizeStreaming(" in ui
assert "writer!!.append(samples)" in ui
print("JNI_ABI_PASS: pinned C++ parameter types agree with Kotlin external declaration")
