package com.deskdot.wear

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** ‹ › stepping and reading the phone's summary (org.json needs Robolectric on the JVM). */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class RemoteLogicTest {
    private val apps = listOf(
        AppItem("clock", "Clock", "time"), AppItem("snake", "Snake", "games"),
        AppItem("pong", "Pong", "games"), AppItem("cat", "Cat", "pets"),
    )

    @Test fun steps_in_the_order_the_watch_lists_them_and_wraps() {
        // games (Pong, Snake), pets (Cat), time (Clock)
        assertEquals("snake", neighbour(apps, "pong", 1)?.id)
        assertEquals("cat", neighbour(apps, "snake", 1)?.id)
        assertEquals("pong", neighbour(apps, "clock", 1)?.id)
        assertEquals("clock", neighbour(apps, "pong", -1)?.id)
    }

    @Test fun with_nothing_on_next_is_the_first_and_previous_the_last() {
        assertEquals("pong", neighbour(apps, "", 1)?.id)
        assertEquals("clock", neighbour(apps, "gone", -1)?.id)
        assertNull(neighbour(emptyList(), "", 1))
    }

    private fun summary(current: Any?, name: String) =
        parseSummary(JSONObject().put("connected", true).put("current", current ?: JSONObject.NULL).put("name", name))

    @Test fun reads_the_app_out_of_the_raw_current_object_from_old_phones() {
        val raw = """{"key":"clock","app":"clock","item":null,"kind":"stream"}"""
        val s = summary(raw, raw)
        assertEquals("clock", s.current)
        assertEquals("", s.name)
        assertEquals("Clock", shownName(s, apps))
    }

    @Test fun reads_a_current_object_and_a_plain_id() {
        assertEquals("snake", summary(JSONObject().put("app", "snake"), "Snake").current)
        assertEquals("Snake", shownName(summary("snake", "Snake"), apps))
        // The phone fell back to the id as the name: still show the real name.
        assertEquals("Snake", shownName(summary("snake", "snake"), apps))
    }

    @Test fun nothing_on_says_so() {
        assertEquals("Nothing on", shownName(summary(null, ""), apps))
    }
}
