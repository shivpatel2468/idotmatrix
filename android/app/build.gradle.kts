// DeskDot for Android: the whole engine (Python, via Chaquopy) runs on the phone as a foreground service and
// owns the panel's BLE link through BleBridge. See docs/adr/0011-android-host-app.md and android/README.md.
//
// Two product flavors share this module (one flavor dimension, "form"):
//   - mobile (default): unchanged phone build — Python 3.13, arm64-v8a only.
//   - wear:             Fossil Gen 6 / Wear OS 3 — Python 3.11 (Chaquopy drops 32-bit ABIs on 3.12+), built for
//                        armeabi-v7a AND arm64-v8a as one universal APK. See docs/adr/0012-wear-armv7-host.md.
// A separate :wear module was considered and rejected: it would duplicate BleBridge, EngineService, BootReceiver
// and the whole Chaquopy source-set wiring for zero behavioural difference in that code between form factors.

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

android {
    namespace = "com.deskdot.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.deskdot.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "3.7.0-beta"
        ndk {
            abiFilters += listOf("arm64-v8a") // every phone from the last ~8 years; the only ABI we vendor wheels for
        }
    }

    flavorDimensions += "form"
    productFlavors {
        create("mobile") {
            dimension = "form"
            // inherits defaultConfig as-is: minSdk 26, arm64-v8a only — bit-for-bit the pre-wear phone build.
        }
        create("wear") {
            dimension = "form"
            minSdk = 30 // Wear OS 3
            ndk {
                abiFilters.clear()
                abiFilters += listOf("armeabi-v7a", "arm64-v8a") // the Fossil Gen 6 is v7a-only; v8a for other Wear 3 watches
            }
            // Signed with the shared gen6-watch debug keystore so the debug APK can be installed directly on the
            // watch (adb install -r); not needed for `mobile`, which uses Android's auto-generated debug key.
            // Path comes from local.properties (`deskdot.wearKeystore`) so the keystore location stays
            // machine-specific and nothing about it is committed.
            localProps.getProperty("deskdot.wearKeystore")?.let { ksPath ->
                signingConfig = signingConfigs.create("wearDebug") {
                    storeFile = file(ksPath)
                    storePassword = "android"
                    keyAlias = "androiddebugkey"
                    keyPassword = "android"
                }
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug") // sideloaded, not published
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    testOptions {
        unitTests {
            isIncludeAndroidResources = true // Robolectric needs merged resources (fonts, themes) to render Compose
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        // a Python 3.13 on the build machine (Chaquopy compiles the app's Python with it)
        localProps.getProperty("deskdot.buildPython")?.let { buildPython(it) }
        // StaticFiles needs the studio as real files on disk
        extractPackages("deskdot_web")
        // NOTE: `pip {}` installs accumulate across defaultConfig + productFlavors (they are not an override like
        // `version`), so every dependency — including ones identical between flavors — is listed per flavor below,
        // not here, to avoid the mobile flavor's cp313 pydantic-core wheel also being fed to the wear (cp311) venv.
    }
    productFlavors {
        getByName("mobile") {
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
        }
        // Chaquopy has no armeabi-v7a build of Python 3.12+ (dropped 32-bit ABIs from 3.12 on; see docs/adr/0012),
        // so the wear flavor pins Python 3.11 — still 3.11 semantics, same deskdot source, no feature cut. The
        // codebase's only 3.12-only syntax (one PEP 695 `def verify[T]`) was rewritten to the equivalent
        // `TypeVar`-based form (src/deskdot/casino/fair.py) so it runs unchanged on 3.11 and 3.13 alike.
        getByName("wear") {
            version = "3.11"
            localProps.getProperty("deskdot.buildPython311")?.let { buildPython(it) }
            pip {
                // cross-compiled for both ABIs the same way as the phone's (android/tools/build-pydantic-core.sh
                // ARCH=armv7|arm64 PY_VERSION=3.11) — NOT YET BUILT, see android/README.md "Wear" section.
                // Unlike the (single-ABI) mobile flavor, `install(path)` can't be used directly here: wear builds
                // two ABIs, and a hard-coded path is fed unconditionally to both per-ABI pip sub-installs, so the
                // wrong-ABI wheel is rejected as "not a supported wheel on this platform". Instead, point pip at
                // the wheels directory and let its own platform-compatibility check pick the matching-ABI file.
                options("--find-links", "wheels")
                install("pydantic-core==2.46.5")
                install("pydantic==2.13.5")
                // confirmed present on Chaquopy's repository (chaquo.com/pypi-13.1) for both ABIs, cp311:
                install("numpy==1.26.2")
                // Pillow stops at 9.2.0 for cp311 on Chaquopy's repository (no 10.x/11.x cp311 wheel exists for
                // either ABI). Audited: every PIL API deskdot uses (Image.Resampling/Transpose, ImageOps.fit /
                // exif_transpose, ImageFilter.UnsharpMask/MedianFilter/GaussianBlur, Image.fromarray/frombuffer)
                // has existed since Pillow 9.1 — no feature is missing, just an older build of the same library.
                install("pillow==9.2.0")
                install("psutil==7.1.3")
                install("fastapi==0.141.1")
                install("starlette==1.7.0")
                install("uvicorn==0.53.0")
                install("h11==0.16.0")
                install("websockets==17.1")
                install("httpx==0.28.1")
                install("python-multipart==0.0.32")
                install("tzdata==2026.4")
            }
        }
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

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.webkit:webkit:1.12.1")

    // Wear UI only (the DeskDot Watch native screens, android/app/src/wear) — never pulled into the mobile flavor.
    "wearImplementation"(platform("androidx.compose:compose-bom:2024.12.01"))
    "wearImplementation"("androidx.compose.ui:ui")
    "wearImplementation"("androidx.compose.ui:ui-graphics")
    "wearImplementation"("androidx.compose.foundation:foundation")
    "wearImplementation"("androidx.activity:activity-compose:1.9.3")
    "wearImplementation"("androidx.lifecycle:lifecycle-runtime-compose:2.8.6")
    "wearImplementation"("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")
    "wearImplementation"("androidx.wear.compose:compose-material:1.4.1")
    "wearImplementation"("androidx.wear.compose:compose-foundation:1.4.1")
    "wearImplementation"("androidx.wear.compose:compose-navigation:1.4.1")
    "wearImplementation"("androidx.wear.tiles:tiles:1.4.1")
    "wearImplementation"("androidx.wear.protolayout:protolayout:1.2.1")
    "wearImplementation"("androidx.wear.protolayout:protolayout-material:1.2.1")
    "wearImplementation"("androidx.wear.watchface:watchface-complications-data-source-ktx:1.2.1")
    "wearImplementation"("com.google.zxing:core:3.5.3")
    "wearImplementation"("androidx.compose.ui:ui-tooling-preview")
    // Talking to the on-watch engine at 127.0.0.1:8765 (REST + the /ws WebSocket for live preview frames).
    "wearImplementation"("com.squareup.okhttp3:okhttp:4.12.0")
    "wearImplementation"("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    // RemoteInputIntentHelper: the manual-MAC pairing fallback and the Apps search pill (voice/handwriting text
    // entry — Wear OS 3 round watches have no full on-screen keyboard IME by default).
    "wearImplementation"("androidx.wear:wear-input:1.1.0")
    "wearImplementation"("androidx.wear:wear-remote-interactions:1.1.0")
    "wearImplementation"("androidx.wear:wear-ongoing:1.0.0")
    "wearImplementation"("androidx.wear:wear-phone-interactions:1.1.0")
    "wearImplementation"("androidx.wear:wear:1.3.0")
    // The Tile (DeskDotTileService) bridges its suspend/coroutine engine calls to the ListenableFuture API
    // androidx.wear.tiles.TileService requires.
    "wearImplementation"("androidx.concurrent:concurrent-futures:1.2.0")
    "wearImplementation"("androidx.wear.watchface:watchface-complications-data-source:1.2.1")
}

// Screenshot tests (DESIGN_SPEC verification: every screen at 416x416, compared by eye against preview.html,
// plus the R1 edge-fade bounds test) — wear-flavor unit tests only, Robolectric + Roborazzi. AGP's unit-test
// configuration naming is `test<Flavor>Implementation` (the "test" prefix comes first), not `<flavor>Test...`.
dependencies {
    "testWearImplementation"("junit:junit:4.13.2")
    "testWearImplementation"("org.robolectric:robolectric:4.13")
    "testWearImplementation"("androidx.test:core:1.6.1")
    "testWearImplementation"("androidx.test.ext:junit:1.2.1")
    "testWearImplementation"("androidx.compose.ui:ui-test-junit4")
    "testWearImplementation"("io.github.takahirom.roborazzi:roborazzi:1.26.0")
    "testWearImplementation"("io.github.takahirom.roborazzi:roborazzi-compose:1.26.0")
}

// `ui-test-manifest`'s own AndroidManifest.xml fragment (declaring the ComponentActivity Compose's
// `createComposeRule()` launches under the hood) must be merged into the *app* variant's manifest, not just be
// on the unit-test compile classpath — Robolectric runs tests against the real merged `wearDebug` manifest. The
// per-variant `wearDebugImplementation` configuration only exists after AGP finishes creating variants, hence
// `afterEvaluate`. This is Google's own documented pattern for Compose + Robolectric screenshot tests (normally
// written as plain `debugImplementation`; scoped to `wearDebugImplementation` here to keep it out of mobile).
afterEvaluate {
    dependencies.add("wearDebugImplementation", "androidx.compose.ui:ui-test-manifest:1.7.6")
}

// Roborazzi normally gets this system property from its own Gradle plugin's `recordRoborazzi<Variant>` task,
// which isn't applied here (see the comment on the Compose compiler wiring above for why module-wide plugins
// are avoided) — wired by hand, scoped to the wear flavor's unit test task only.
tasks.matching { it.name == "testWearDebugUnitTest" }.configureEach {
    (this as Test).systemProperty("roborazzi.test.record", "true")
}

// Enable Compose for the wear flavor only, without changing the phone build.
//
// `id("org.jetbrains.kotlin.plugin.compose")` in the shared `plugins {}` block was tried first, but it attaches
// the Compose IR compiler transform to *every* Kotlin compile task in the module unconditionally (confirmed:
// removing `buildFeatures.compose` had no effect on `compileMobileDebugKotlin`, which still failed with
// "Compose Compiler requires the Compose Runtime to be on the class path" because mobile has no Compose runtime
// on its classpath by design). So instead the Compose compiler plugin jar is added directly to the Kotlin
// compiler's `pluginClasspath` only for the Kotlin compile tasks of the `wear` flavor — the standard low-level
// mechanism `org.jetbrains.kotlin.plugin.compose` itself uses, just scoped by hand per variant.
val composeCompilerPlugin: Configuration by configurations.creating
dependencies {
    composeCompilerPlugin("org.jetbrains.kotlin:kotlin-compose-compiler-plugin-embeddable:2.0.21")
}
tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
    if (name.contains("Wear")) {
        pluginClasspath.from(composeCompilerPlugin)
    }
}
