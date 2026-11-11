package com.deskdot.app

import java.io.File
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64

/**
 * Is this APK really a DeskDot release? (docs/adr/0017-signed-release-checksums.md)
 *
 * Every release's `checksums.txt` is signed by the owner's release key (ECDSA P-256 over SHA-256); the signature is
 * the `checksums.txt.sig` asset (base64 of the DER signature). The engine (src/deskdot/updates.py) checks it before
 * calling [Updater.install]; this checks it again, in Kotlin, with the same built-in public key, plus the APK's
 * SHA-256 against its line in that verified file. Plain JVM (no Android classes), so it is unit-tested on the JVM:
 * `android/app/src/test/.../ReleaseVerifierTest.kt`.
 *
 * `java.security.Signature("SHA256withECDSA")` and `KeyFactory("EC")` exist on every Android version DeskDot runs
 * on (minSdk 26), so no library is needed. `java.util.Base64` is API 26+.
 */
object ReleaseVerifier {
    /** The public half of the release key, base64 SubjectPublicKeyInfo. Must equal `RELEASE_KEYS` in
     *  src/deskdot/update_signature.py (tests/test_update_signature.py checks they match). */
    val RELEASE_KEYS = listOf(
        "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEjyM+LJLWaOWUjObKCIXsAQgpYQCG" +
            "gTFqT00Hi9dO1AEgnlaH6wcxO1Lk8LHBSvUf0Uum+37mdPCwZCrWSnRgdw==",
    )

    enum class Result { OK, NO_SIGNATURE, BAD_SIGNATURE, NOT_LISTED, MISMATCH }

    private val LINE = Regex("""^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$""")

    /** Does `signatureFile` (the `checksums.txt.sig` asset) sign exactly these `checksums` bytes with one of [keys]? */
    fun checksumsAreSigned(checksums: ByteArray, signatureFile: ByteArray, keys: List<String> = RELEASE_KEYS): Boolean {
        val der = try {
            Base64.getDecoder().decode(String(signatureFile, Charsets.US_ASCII).filterNot { it.isWhitespace() })
        } catch (e: IllegalArgumentException) {
            return false
        }
        if (der.isEmpty()) return false
        return keys.any { key ->
            try {
                val pub = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Base64.getDecoder().decode(key)))
                Signature.getInstance("SHA256withECDSA").run {
                    initVerify(pub)
                    update(checksums)
                    verify(der)
                }
            } catch (e: Exception) { // a malformed signature throws SignatureException: that's a no
                false
            }
        }
    }

    /** `sha256sum` lines → {file name: lower-case hex}. */
    fun parseChecksums(text: String): Map<String, String> = text.lineSequence()
        .mapNotNull { LINE.find(it.trim()) }
        .associate { m -> m.groupValues[2].substringAfterLast('/') to m.groupValues[1].lowercase() }

    fun sha256(file: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(1 shl 16)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    /** The whole check for one downloaded APK. [Result.OK] is the only answer that may be installed. */
    fun verify(apk: File, checksums: File, signature: File, keys: List<String> = RELEASE_KEYS): Result {
        if (!signature.isFile) return Result.NO_SIGNATURE
        if (!checksums.isFile) return Result.NOT_LISTED
        val sums = checksums.readBytes()
        if (!checksumsAreSigned(sums, signature.readBytes(), keys)) return Result.BAD_SIGNATURE
        val expected = parseChecksums(String(sums, Charsets.UTF_8))[apk.name] ?: return Result.NOT_LISTED
        return if (sha256(apk) == expected) Result.OK else Result.MISMATCH
    }
}
