package com.deskdot.app

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.core.content.FileProvider
import java.io.File
import java.security.MessageDigest

/**
 * In-app updates, Android side (the engine's src/deskdot/updates.py does the rest).
 *
 * The engine checks GitHub Releases, downloads `DeskDot-<version>.apk` into `files/data/updates/` and verifies its
 * SHA-256 against the release's checksums; then it calls, from Python:
 *
 *     jclass("com.deskdot.app.Updater").install(path)
 *
 * which opens Android's package installer for that file (through [FileProvider]; authority `<package>.updates`,
 * res/xml/update_paths.xml). Returns "started", "permission" (DeskDot may not install apps yet: the matching
 * settings screen was opened), "signature" (the APK isn't signed with this app's key, so Android would refuse it)
 * or "missing".
 */
object Updater {
    private const val TAG = "DeskDot"

    @Volatile
    private var context: Context? = null

    @JvmStatic
    fun init(c: Context) {
        context = c.applicationContext
    }

    @JvmStatic
    fun install(path: String): String {
        val c = context ?: return "missing"
        val apk = File(path)
        if (!apk.isFile) return "missing"
        if (!sameSigner(c, apk)) return "signature"
        if (Build.VERSION.SDK_INT >= 26 && !c.packageManager.canRequestPackageInstalls()) {
            val settings = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${c.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            c.startActivity(settings)
            return "permission"
        }
        val uri = FileProvider.getUriForFile(c, "${c.packageName}.updates", apk)
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        c.startActivity(intent)
        return "started"
    }

    /** The downloaded APK must carry the same signing certificate as the installed app. */
    private fun sameSigner(c: Context, apk: File): Boolean = try {
        val mine = signers(packageInfo(c.packageManager, null, c.packageName))
        val theirs = signers(packageInfo(c.packageManager, apk.absolutePath, null))
        mine.isNotEmpty() && mine == theirs
    } catch (t: Throwable) {
        Log.w(TAG, "can't read the update's signature", t)
        false
    }

    @Suppress("DEPRECATION")
    @SuppressLint("PackageManagerGetSignatures")
    private fun packageInfo(pm: PackageManager, archive: String?, name: String?): PackageInfo? {
        val flags = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
        return if (archive != null) pm.getPackageArchiveInfo(archive, flags) else pm.getPackageInfo(name!!, flags)
    }

    @Suppress("DEPRECATION")
    private fun signers(info: PackageInfo?): Set<String> {
        if (info == null) return emptySet()
        val sigs = if (Build.VERSION.SDK_INT >= 28) {
            info.signingInfo?.let { if (it.hasMultipleSigners()) it.apkContentsSigners else it.signingCertificateHistory }
        } else {
            info.signatures
        } ?: return emptySet()
        val sha = MessageDigest.getInstance("SHA-256")
        return sigs.map { s -> sha.digest(s.toByteArray()).joinToString("") { "%02x".format(it) } }.toSet()
    }
}
