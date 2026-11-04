// DeskDot for Wear OS: a light remote of the phone app (android/wear/SPEC.md). It talks to the phone over the
// Wearable Data Layer; the phone's WearBridgeService answers from its engine. Same applicationId and release
// signature as the phone app, so Google pairs the two (I-WEAR-3).

import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val repoRoot = rootProject.projectDir.parentFile
val deskdotVersion: String = Regex("""__version__ = "([^"]+)"""")
    .find(File(repoRoot, "src/deskdot/__init__.py").readText())!!.groupValues[1]
val deskdotVersionCode: Int = deskdotVersion.substringBefore("-").split(".").map { it.toInt() }
    .let { (major, minor, patch) -> major * 10000 + minor * 100 + patch }

// The same git-ignored android/keystore.properties as the phone app; storeFile resolves like the phone's
// (relative to android/app), so both APKs carry one signature.
val keystoreProps = Properties().apply {
    rootProject.file("keystore.properties").takeIf { it.isFile }?.inputStream()?.use { load(it) }
}

android {
    namespace = "com.deskdot.wear"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.deskdot.app"
        minSdk = 30
        targetSdk = 34
        versionCode = deskdotVersionCode
        versionName = deskdotVersion
    }

    signingConfigs {
        keystoreProps.getProperty("storeFile")?.let { path ->
            create("release") {
                storeFile = File(path).takeIf { it.isAbsolute } ?: rootProject.file("app/$path")
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug").also {
                logger.warn("android/keystore.properties not found: the watch APK is signed with the DEBUG key")
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
    buildFeatures {
        compose = true
    }
    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.wear.compose:compose-material:1.4.1")
    implementation("androidx.wear.compose:compose-foundation:1.4.1")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.wear:wear:1.3.0")
    implementation("com.google.android.gms:play-services-wearable:18.2.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.9.0")

    // Screenshots of every screen at the watch's 416 × 416 px (JVM, no device needed).
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.13")
    testImplementation("androidx.compose.ui:ui-test-junit4:1.7.6")
    debugImplementation("androidx.compose.ui:ui-test-manifest:1.7.6")
}
