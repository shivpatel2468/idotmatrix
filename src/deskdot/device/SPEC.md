# Device spec (`src/deskdot/device/`)

Parent: [root SPEC.md](../../../SPEC.md). How and why: [docs/HARDWARE_PROTOCOL.md](../../../docs/HARDWARE_PROTOCOL.md),
ADRs [0003](../../../docs/adr/0003-own-ble-transport.md), [0004](../../../docs/adr/0004-latest-frame-wins.md),
[0009](../../../docs/adr/0009-paced-writes-and-ack-flow-control.md),
[0013](../../../docs/adr/0013-user-release-of-the-panel.md).

## Purpose

Keep one calm, persistent Bluetooth LE link to the panel and put the newest visual on it as fast as the panel's
physics allow. `protocol.py` = pure byte encoders; `base.Device` = the only writer (scheduler, reconnect supervisor,
replay); backends (`ble.py` desktop, `android.py`, `web.py`, `sim.py`) implement `_connect / _disconnect / _write`.

## Requirements

- **R-DEV-1** Protocol bytes are pinned: every command, PNG frame header and GIF chunk header matches the reference
  library or a hardware capture. Tests: `tests/test_protocol.py::test_short_commands`,
  `tests/test_protocol.py::test_image_upload_header`, `tests/test_protocol.py::test_image_upload_multichunk_flags`,
  `tests/test_protocol.py::test_gif_upload_chunks`, `tests/test_protocol.py::test_validation`.
- **R-DEV-2** Latest frame wins: a newer frame replaces an unsent one (and supersedes a queued GIF); at most one
  un-acked frame is in flight. Tests: `tests/test_engine.py::test_latest_frame_wins`,
  `tests/test_engine.py::test_frame_supersedes_queued_gif`, `tests/test_web_device.py::test_latest_frame_wins`.
- **R-DEV-3** Write priority: commands (FIFO) → GIF → pixels → frame. Tests:
  `tests/test_engine.py::test_commands_jump_the_frame_queue`.
- **R-DEV-4** Packets of one message are paced (`packet_gap_ms`), each GIF chunk waits for its ack, and a GIF upload is
  never abandoned midway. Tests: `tests/test_engine.py::test_gif_upload_is_never_abandoned_midway`,
  `tests/test_web_device.py::test_frames_are_split_into_paced_packets_one_at_a_time`,
  `tests/test_web_device.py::test_gif_chunks_wait_for_their_ack`,
  `tests/test_android_device.py::test_frames_are_split_into_paced_packets_one_at_a_time`.
- **R-DEV-5** On link loss the device reconnects by itself (back-off 1 → 20 s, a hung connect abandoned after 45 s)
  and replays brightness, power and the last visual. Tests:
  `tests/test_engine.py::test_a_hung_connect_is_abandoned_and_retried`,
  `tests/test_web_device.py::test_link_loss_reconnects_and_replays_the_screen`,
  `tests/test_android_device.py::test_link_loss_reconnects_and_replays_the_screen`.
- **R-DEV-6** Failures are diagnosed in plain words (`reason`, `hint`, next retry); "not found" three times in a row
  means *busy elsewhere*. *Reconnect now* cuts the back-off short without disconnecting a good link.
  Tests: `tests/test_device_connection.py::test_classify`,
  `tests/test_device_connection.py::test_repeated_not_found_means_busy_with_the_other_apps_named`,
  `tests/test_device_connection.py::test_failure_is_published_with_reason_hint_and_retry_time`,
  `tests/test_device_connection.py::test_reconnect_now_cuts_the_back_off_short_without_disconnecting`,
  `tests/test_device_connection.py::test_reconnect_if_down_leaves_a_good_link_alone`.
- **R-DEV-7** Only the user can release the panel; after a release the device stops reconnecting until the user takes
  it back. Tests: `tests/test_device_connection.py::test_release_stops_reconnecting_until_connect`,
  `tests/test_device_connection.py::test_reconnect_takes_a_released_panel_back`.
- **R-DEV-8** `pause_writes()` (tab hand-over, update) finishes the item in flight and then sends nothing.
  Tests: `tests/test_device_connection.py::test_pause_writes_finishes_the_item_in_flight_then_sends_nothing`.
- **R-DEV-9** `/api/health` tells the web app whether this computer's DeskDot holds the panel (CORS + Private Network
  Access for idotmatrix.com only). Tests: `tests/test_device_connection.py::test_health_probe_for_the_web_app`.
- **R-DEV-10** Baked GIFs stay under the 40 KB budget; frames are truecolour PNG (never palette PNG).
  Tests: `tests/test_gfx.py::test_gif_budget_is_a_hard_limit`.

## Invariants

- **I-DEV-1** The engine is the only process that owns the link. `bleak` is imported only in `device/`.
- **I-DEV-2** Never disconnect voluntarily (the panel shows a pairing screen). The only exception is the user's
  explicit *Release the panel* (ADR 0013).
- **I-DEV-3** Never queue frames FIFO toward the panel.
- **I-DEV-4** `diy_mode(1)` is sent only when entering DIY from another mode (it blanks the panel).
- **I-DEV-5** Link physics (pacing, one frame in flight, chunk acks, GIF cool-down 3 s, the 40 KB budget) are not
  "optimised" without re-testing on the panel and recording it in HARDWARE_PROTOCOL.md.
- **I-DEV-6** Any change to `protocol.py` comes with pinned bytes in `tests/test_protocol.py`.

## Interfaces

`Device.show_frame / show_gif / command / set_pixels / retry_now / release / pause_writes`; `state.device` (link
stats, `reason`, `hint`, `rssi`); `POST /api/device/link`, `POST /api/device/reconnect`, `GET /api/device/scan`,
`POST /api/device/raw`, `GET /api/health`. Notifications on `fa03`, writes on `fa02`.

## Open questions

- I-DEV-1 has no automated import-boundary test (grep shows `bleak` only in `device/ble.py` today).
- Whether `packet_gap_ms` can drop below 30 ms (HARDWARE_PROTOCOL.md § Unverified).

Last verified: 2026-10-29
