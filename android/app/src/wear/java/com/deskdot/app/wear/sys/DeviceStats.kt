package com.deskdot.app.wear.sys

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Process
import java.io.RandomAccessFile

/**
 * DESIGN_SPEC §5.9 "Engine" rows marked **Shell**: CPU, RAM, battery temperature and drain. None of these have
 * an engine endpoint (E3 in the spec explicitly says "Nothing for CPU and RAM" — the shell measures them
 * natively), so this reads them directly from the OS, the same way a profiler would.
 */
class DeviceStats(private val context: Context) {
    private var lastCpuSampleAt = 0L
    private var lastCpuJiffies = 0L
    private var lastBatteryPct: Int? = null
    private var lastBatteryAt = 0L

    /** CPU percent used by this process since the previous call (0 the first time: there is no delta yet).
     * DESIGN_SPEC: "the delta of /proc/self/stat utime + stime over 2 s / (2 s * 4 cores)". */
    fun cpuPercent(cores: Int = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)): Double {
        val (jiffies, now) = runCatching {
            RandomAccessFile("/proc/self/stat", "r").use { f ->
                val fields = f.readLine().substringAfter(')').trim().split(' ')
                // After the ")", fields are 0-indexed starting at state(2); utime=13, stime=14 in `man proc` (1-based
                // from the start of the whole line), i.e. indices 11 and 12 here (0-based, after the comm field).
                val utime = fields.getOrNull(11)?.toLongOrNull() ?: 0L
                val stime = fields.getOrNull(12)?.toLongOrNull() ?: 0L
                (utime + stime) to System.currentTimeMillis()
            }
        }.getOrDefault(0L to System.currentTimeMillis())

        val result = if (lastCpuSampleAt == 0L || now <= lastCpuSampleAt) {
            0.0
        } else {
            val jiffiesPerSec = 100.0 // Linux default USER_HZ; Android does not expose sysconf(_SC_CLK_TCK) easily
            val deltaJiffies = (jiffies - lastCpuJiffies).coerceAtLeast(0)
            val deltaSeconds = (now - lastCpuSampleAt) / 1000.0
            val busySeconds = deltaJiffies / jiffiesPerSec
            (busySeconds / (deltaSeconds * cores) * 100.0).coerceIn(0.0, 100.0)
        }
        lastCpuJiffies = jiffies
        lastCpuSampleAt = now
        return result
    }

    /** Total PSS (Python + JVM + native) in MB, per DESIGN_SPEC: "ActivityManager.getProcessMemoryInfo(myPid)[0].totalPss". */
    fun ramMb(): Int = runCatching {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return 0
        val info: Array<android.os.Debug.MemoryInfo?>? = am.getProcessMemoryInfo(intArrayOf(Process.myPid()))
        (info?.firstOrNull()?.totalPss ?: 0) / 1024
    }.getOrDefault(0)

    /** Battery temperature in Celsius, from the last sticky ACTION_BATTERY_CHANGED broadcast (no receiver needed
     * for a one-shot read: registering a null receiver with this filter returns the last sticky intent). */
    fun batteryTempC(): Double? {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return null
        val tenths = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
        return if (tenths == Int.MIN_VALUE) null else tenths / 10.0
    }

    fun batteryPercent(): Int? {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return null
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        return if (level < 0 || scale <= 0) null else (level * 100 / scale)
    }

    fun isCharging(): Boolean {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return false
        val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        return status == BatteryManager.BATTERY_STATUS_CHARGING || status == BatteryManager.BATTERY_STATUS_FULL
    }

    /** Percent-per-hour drain since the previous call (negative while discharging), or null on the first call,
     * while charging, or if less than 30s has passed (too noisy below that). DESIGN_SPEC: "the battery level
     * delta over the last 10 minutes while unplugged" — approximated here as an instantaneous rate between
     * polls, extrapolated to a per-hour figure, since this screen is only sampled while visible (§5.9: "every
     * 2 s while visible"), not continuously in the background. */
    fun drainPercentPerHour(): Double? {
        val pct = batteryPercent() ?: return null
        val now = System.currentTimeMillis()
        val result = if (isCharging() || lastBatteryAt == 0L || now - lastBatteryAt < 30_000) {
            null
        } else {
            val deltaPct = pct - (lastBatteryPct ?: pct)
            val deltaHours = (now - lastBatteryAt) / 3_600_000.0
            if (deltaHours <= 0) null else deltaPct / deltaHours
        }
        lastBatteryPct = pct
        lastBatteryAt = now
        return result
    }
}
