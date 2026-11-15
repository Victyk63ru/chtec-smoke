plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "com.openmoss.ttsnano.onnxruntime"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.openmoss.ttsnano.voiceclonetest"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.4.0-a-smoke"
        ndk { abiFilters += listOf("arm64-v8a") }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.20.0")
    implementation("io.github.eix128:sentencepiece4j:1.0.2")
}
