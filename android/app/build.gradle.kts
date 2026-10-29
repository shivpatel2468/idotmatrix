// DeskDot for Android: the whole engine (Python, via Chaquopy) runs on the phone as a foreground service and
// owns the panel's BLE link through BleBridge. See docs/adr/0011-android-host-app.md and android/README.md.

import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

val repoRoot = rootProject.projectDir.parentFile
val localProps = Properties().apply {
    rootProject.file("local.properties").takeIf { it.isFile }?.inputStream()?.use { load(it) }
}
val studioOut = layout.buildDirectory.dir("studio")

// One version for everything: src/deskdot/__init__.py. versionCode = major*10000 + minor*100 + patch (3.8.0 → 30800),
// so it only ever goes up (Android refuses to update to a lower versionCode).
val deskdotVersion: String = Regex("""__version__ = "([^"]+)"""")
    .find(File(repoRoot, "src/deskdot/__init__.py").readText())!!.groupValues[1]
val deskdotVersionCode: Int = deskdotVersion.substringBefore("-").split(".").map { it.toInt() }
    .let { (major, minor, patch) -> major * 10000 + minor * 100 + patch }

// Release signing: android/keystore.properties (git-ignored; storeFile, storePassword, keyAlias, keyPassword).
// Never in git, never in CI. Without it, release builds fall back to the debug key (fine for testing only).
val keystoreProps = Properties().apply {
    rootProject.file("keystore.properties").takeIf { it.isFile }?.inputStream()?.use { load(it) }
}

android {
    namespace = "com.deskdot.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.deskdot.app"
        minSdk = 26
        targetSdk = 35
        versionCode = deskdotVersionCode
        versionName = deskdotVersion
        ndk {
            abiFilters += listOf("arm64-v8a") // every phone from the last ~8 years; the only ABI we vendor wheels for
        }
    }

    signingConfigs {
        if (keystoreProps.getProperty("storeFile") != null) {
            create("release") {
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug").also {
                logger.warn("android/keystore.properties not found: the release APK is signed with the DEBUG key")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        // a Python 3.13 on the build machine (Chaquopy compiles the app's Python with it)
        localProps.getProperty("deskdot.buildPython")?.let { buildPython(it) }
        pip {
            // Rust extension with no official Android build: cross-compiled once, see android/README.md
            install("wheels/pydantic_core-2.46.5-cp313-cp313-android_24_arm64_v8a.whl")
            install("pydantic==2.13.5")
            // Android wheels from Chaquopy's repository (numpy 1.26 is tested: docs/adr/0011)
            install("numpy==1.26.2")
            install("pillow==11.0.0")
            install("psutil==7.1.3")
            // pure Python; plain uvicorn (no uvloop/httptools on Android)
            install("fastapi==0.141.1")
            install("starlette==1.7.0")
            install("uvicorn==0.53.0")
            install("h11==0.16.0")
            install("websockets==17.1")
            install("httpx==0.28.1")
            install("python-multipart==0.0.32")
            install("tzdata==2026.4")
        }
        // StaticFiles needs the studio as real files on disk
        extractPackages("deskdot_web")
    }
    sourceSets {
        getByName("main") {
            srcDir(File(repoRoot, "src"))
            srcDir(studioOut)
        }
    }
}

// The built studio (web/dist, from `npm run build`) packaged as the `deskdot_web` Python package.
val syncStudio by tasks.registering(Sync::class) {
    val dist = File(repoRoot, "web/dist")
    doFirst {
        check(File(dist, "index.html").isFile) { "web/dist is missing: run `cd web && npm run build` first" }
    }
    from(dist) { into("deskdot_web/dist") }
    from(resources.text.fromString("\"\"\"The DeskDot studio (web/dist), bundled for the Android app.\"\"\"\n")) {
        rename { "__init__.py" }
        into("deskdot_web")
    }
    into(studioOut)
}
tasks.named("preBuild") { dependsOn(syncStudio) }
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("PythonSources") }.configureEach {
    dependsOn(syncStudio)
}

// DeskDot-<version>.apk next to the usual output (the name the in-app updater looks for on GitHub)
android.applicationVariants.all {
    val variant = this
    outputs.all {
        (this as com.android.build.gradle.internal.api.BaseVariantOutputImpl).outputFileName =
            if (variant.buildType.name == "release") "DeskDot-${variant.versionName}.apk"
            else "DeskDot-${variant.versionName}-${variant.buildType.name}.apk"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.webkit:webkit:1.12.1")
}
