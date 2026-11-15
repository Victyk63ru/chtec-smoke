from pathlib import Path
root=Path(__file__).resolve().parents[1]
checks={
    'app/build.gradle.kts':'onnxruntime-android:1.20.0',
    'app/src/main/java/com/openmoss/ttsnano/onnxruntime/MainActivity.kt':'MossOnnxDemoEngine(root, cacheDir',
    'app/src/main/java/com/openmoss/ttsnano/onnxruntime/ModelManager.kt':'Content-Range',
    'app/src/main/java/com/openmoss/ttsnano/onnxruntime/SentencePieceTokenizer.kt':'encodeNormalized',
    '.github/workflows/build-apk.yml':'gradle :app:assembleDebug',
    'scripts/fetch_upstream.sh':'31f42bae0a181849864c7ee39e8b88990909065f',
}
for path,fragment in checks.items():
    f=root/path
    assert f.is_file(),f'MISSING {path}'
    assert fragment in f.read_text(encoding='utf8'),f'MISSING {fragment} in {path}'
    print('OK',path)
print('Static packaging inspection passed; NOT an Android compile or runtime test')
