#!/usr/bin/env python3
"""Minimal, strict patch to upstream MOSS engine for optional user voice codes.
The upstream Kotlin source is verified by Git blob ID before this script runs.
"""
from pathlib import Path

target=Path("app/src/main/java/com/openmoss/ttsnano/onnxruntime/MossOnnxDemoEngine.kt")
s=target.read_text(encoding="utf-8")
replacements=[
    ('        voice: String = "Junhao",\n',
     '        voice: String = "Junhao",\n        promptAudioCodes: List<IntArray>? = null,\n'),
    ('        val inputRows = buildInputRows(textTokenIds, voice)\n',
     '        val inputRows = buildInputRows(textTokenIds, voice, promptAudioCodes)\n'),
    ('    private fun buildInputRows(textTokenIds: IntArray, voice: String): InputRows {\n',
     '    private fun buildInputRows(textTokenIds: IntArray, voice: String, overrideAudioCodes: List<IntArray>?): InputRows {\n'),
    ('        val promptAudioCodes = selectBuiltinVoicePromptAudioCodes(voice)\n',
     '        val promptAudioCodes = overrideAudioCodes ?: selectBuiltinVoicePromptAudioCodes(voice)\n'),
]
for old,new in replacements:
    n=s.count(old)
    if n!=1: raise SystemExit(f'PATCH_FAIL matched {n} times: {old!r}')
    s=s.replace(old,new)
target.write_text(s,encoding="utf-8")
print("VOICE_PATCH_OK: optional promptAudioCodes supported; upstream algorithm otherwise unchanged")
