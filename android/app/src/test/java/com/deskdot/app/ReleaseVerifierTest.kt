package com.deskdot.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64

/** ReleaseVerifier on the JVM with throwaway keys made here (never the real release key). ADR 0017. */
class ReleaseVerifierTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private fun newKey(): KeyPair = KeyPairGenerator.getInstance("EC").apply {
        initialize(ECGenParameterSpec("secp256r1"))
    }.generateKeyPair()

    private val key = newKey()
    private val other = newKey()
    private fun pub(k: KeyPair) = Base64.getEncoder().encodeToString(k.public.encoded)
    private val trusted get() = listOf(pub(key))

    private fun sign(data: ByteArray, k: KeyPair = key): ByteArray {
        val der = Signature.getInstance("SHA256withECDSA").run {
            initSign(k.private)
            update(data)
            sign()
        }
        return (Base64.getEncoder().encodeToString(der) + "\n").toByteArray(Charsets.US_ASCII)
    }

    private fun hex(b: ByteArray) = MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }

    private class Release(val apk: File, val sums: File, val sig: File)

    private fun release(
        apkBytes: ByteArray = "the real apk".toByteArray(),
        listed: ByteArray = apkBytes,
        sigOver: ((ByteArray) -> ByteArray)? = null,
        signer: KeyPair = key,
        signed: Boolean = true,
    ): Release {
        val dir = tmp.newFolder()
        val apk = File(dir, "DeskDot-3.11.0.apk").apply { writeBytes(apkBytes) }
        val text = "${hex("mac".toByteArray())}  DeskDot-3.11.0-macOS-arm64.dmg\n${hex(listed)}  DeskDot-3.11.0.apk\n"
        val sums = File(dir, "checksums.txt").apply { writeText(text) }
        val sig = File(dir, "checksums.txt.sig")
        if (signed) sig.writeBytes(sign(sigOver?.invoke(sums.readBytes()) ?: sums.readBytes(), signer))
        return Release(apk, sums, sig)
    }

    private fun check(r: Release) = ReleaseVerifier.verify(r.apk, r.sums, r.sig, trusted)

    @Test
    fun goodSignatureAndMatchingFileIsOk() {
        assertEquals(ReleaseVerifier.Result.OK, check(release()))
    }

    @Test
    fun missingSignatureIsRefused() {
        assertEquals(ReleaseVerifier.Result.NO_SIGNATURE, check(release(signed = false)))
    }

    @Test
    fun signatureByAnotherKeyIsRefused() {
        assertEquals(ReleaseVerifier.Result.BAD_SIGNATURE, check(release(signer = other)))
    }

    @Test
    fun garbageSignatureIsRefused() {
        val r = release()
        r.sig.writeText("not base64 at all!")
        assertEquals(ReleaseVerifier.Result.BAD_SIGNATURE, check(r))
        r.sig.writeText("")
        assertEquals(ReleaseVerifier.Result.BAD_SIGNATURE, check(r))
        r.sig.writeText(Base64.getEncoder().encodeToString(byteArrayOf(0x30, 0x02, 0x02, 0x00)))
        assertEquals(ReleaseVerifier.Result.BAD_SIGNATURE, check(r))
    }

    @Test
    fun tamperedChecksumsAreRefused() {
        // the APK and its line were both swapped; the signature is over the original checksums.txt
        val evil = "an apk someone else built".toByteArray()
        val r = release(apkBytes = evil, listed = evil, sigOver = { it.toString(Charsets.UTF_8).replace(hex(evil), hex("the real apk".toByteArray())).toByteArray() })
        assertEquals(ReleaseVerifier.Result.BAD_SIGNATURE, check(r))
    }

    @Test
    fun tamperedFileIsRefused() {
        val r = release(apkBytes = "a different apk".toByteArray(), listed = "the real apk".toByteArray())
        assertEquals(ReleaseVerifier.Result.MISMATCH, check(r))
    }

    @Test
    fun anApkNotListedIsRefused() {
        val r = release()
        val renamed = File(r.apk.parentFile, "DeskDot-9.9.9.apk").apply { writeBytes(r.apk.readBytes()) }
        assertEquals(ReleaseVerifier.Result.NOT_LISTED, ReleaseVerifier.verify(renamed, r.sums, r.sig, trusted))
    }

    @Test
    fun noTrustedKeyMeansNothingVerifies() {
        val r = release()
        assertFalse(ReleaseVerifier.checksumsAreSigned(r.sums.readBytes(), r.sig.readBytes(), emptyList()))
        assertTrue(ReleaseVerifier.checksumsAreSigned(r.sums.readBytes(), r.sig.readBytes(), listOf(pub(other), pub(key))))
    }

    @Test
    fun theBuiltInKeyIsAValidP256Key() {
        val spec = java.security.spec.X509EncodedKeySpec(Base64.getDecoder().decode(ReleaseVerifier.RELEASE_KEYS.single()))
        val k = java.security.KeyFactory.getInstance("EC").generatePublic(spec) as java.security.interfaces.ECPublicKey
        assertEquals(256, k.params.order.bitLength())
    }
}
