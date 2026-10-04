/* DeskDot web app add-on: camera / screen / microphone capture (docs/WEB_APP.md).
 *
 * The engine (a Web Worker) can't open a camera, share a screen or record sound — only the page can, and only with
 * the user's permission. So the engine asks (providers/webmedia.py → worker.js `deskdotMedia`) and this script
 * captures, shrinks and forwards:
 *
 *   worker → page   {t:"media", op:"want", kind, opts}   kind: "camera" {index} | "screen" {} | "audio" {source}
 *                   {t:"media", op:"stop", kind}         the app that needed it left the panel: release it now
 *   page → worker   {t:"media-frame", kind, w, h, data}  RGB bytes, ≤ 192 px on the long side, ≤ 10 fps
 *                   {t:"media-audio", sr, source, data}  the newest 2048 float32 samples (~23×/s)
 *                   {t:"media-state", kind, state, detail}
 *                   {t:"media-hello"}                    on load: the engine repeats what it still wants
 *
 * States: idle → waiting (needs a click: screen sharing always does, camera / mic until allowed once) → starting →
 * live; or denied / error / stopped / unsupported. A camera or mic the user already allowed starts by itself.
 *
 * The studio shows the prompt (web/src/components/MediaPrompt.tsx) through `window.DeskDotMedia`:
 *   snapshot() → {caps, camera:{wanted, state, detail, source}, screen:{…}, audio:{…}}
 *   start(kind, opts?)  — call it straight from a click (getDisplayMedia needs the user gesture)
 *   stop(kind)          — "Stop sharing" (the engine keeps wanting it; the card offers to share again)
 * and a `deskdot-media` window event (detail = snapshot()) on every change.
 *
 * Frames come from MediaStreamTrackProcessor where the browser has it (not throttled in a background tab), else a
 * <video> + timer. Sound goes through a ScriptProcessorNode (runs on the audio clock, also in a background tab).
 */
(function () {
  "use strict";
  const host = window.DeskDotHost;
  if (!host) return;
  const md = navigator.mediaDevices;
  const ua = navigator.userAgent || "";
  const mobile = (navigator.userAgentData && navigator.userAgentData.mobile) || /Android|iPhone|iPad|iPod|Mobile/i.test(ua);
  const caps = {
    secure: window.isSecureContext !== false,
    camera: !!(md && md.getUserMedia),
    mic: !!(md && md.getUserMedia),
    // phones and tablets can't share their screen with a page (no getDisplayMedia on Android / iOS)
    screen: !!(md && md.getDisplayMedia) && !mobile,
  };
  caps.systemAudio = caps.screen && !/Firefox\//.test(ua); // Firefox shares no audio with getDisplayMedia

  const FPS = { camera: 10, screen: 8 };
  const SIDE = { camera: 160, screen: 192 };
  const S = {};
  for (const k of ["camera", "screen", "audio"])
    S[k] = { wanted: false, opts: {}, state: "idle", detail: "", source: "", stream: null, stopPump: null, token: 0 };

  // ------------------------------------------------------------------------------------------- state
  function snapshot() {
    const out = { caps: { ...caps } };
    for (const [k, s] of Object.entries(S)) out[k] = { wanted: s.wanted, state: s.state, detail: s.detail, source: s.source };
    return out;
  }
  function emit() {
    try {
      window.dispatchEvent(new CustomEvent("deskdot-media", { detail: snapshot() }));
    } catch (e) {
      /* old browsers: the studio polls snapshot() */
    }
  }
  function setState(kind, state, detail) {
    const s = S[kind];
    s.state = state;
    s.detail = detail || "";
    if (s.wanted) host.post({ t: "media-state", kind, state, detail: s.detail });
    emit();
  }
  /** "system" sound needs getDisplayMedia; elsewhere (phones, Firefox) the microphone stands in. */
  function audioSource(opts) {
    return opts && opts.source === "system" && caps.systemAudio ? "system" : "mic";
  }

  async function granted(name) {
    try {
      const p = await navigator.permissions.query({ name });
      return p.state === "granted";
    } catch (e) {
      return false; // Firefox doesn't know "camera" / "microphone": ask with a click
    }
  }

  // ------------------------------------------------------------------------------------------- engine requests
  host.onMessage((m) => {
    if (!m || m.t !== "media" || !S[m.kind]) return;
    const s = S[m.kind];
    if (m.op === "stop") {
      s.wanted = false;
      closeStream(m.kind);
      s.state = "idle";
      s.detail = "";
      return emit();
    }
    if (m.op !== "want") return;
    const opts = m.opts || {};
    const same = JSON.stringify(opts) === JSON.stringify(s.opts);
    s.wanted = true;
    s.opts = opts;
    if (s.stream && same) return setState(m.kind, s.state, s.detail); // repeated (hello): tell the engine again
    closeStream(m.kind);
    autoStart(m.kind);
  });

  async function autoStart(kind) {
    const s = S[kind];
    if (!caps.secure) return setState(kind, "unsupported", "Camera, screen and microphone need a secure (https) page.");
    if (kind === "screen") {
      if (!caps.screen)
        return setState(kind, "unsupported", mobile
          ? "Phones and tablets can't share their screen with a web page. Use Screen Mirror from the desktop app."
          : "This browser can't share the screen. Use Chrome or Edge on a computer.");
      return setState(kind, "waiting", "Choose a screen, window or tab to mirror on the panel.");
    }
    if (kind === "camera") {
      if (!caps.camera) return setState(kind, "unsupported", "This browser has no camera access.");
      if (await granted("camera")) return start(kind); // allowed before: no prompt, start right away
      return S[kind].wanted && !S[kind].stream ? setState(kind, "waiting", "Camera Mirror needs your camera.") : undefined;
    }
    // audio
    const src = audioSource(s.opts);
    s.source = src;
    if (src === "system") return setState(kind, "waiting", "Share a tab (or your screen) that is playing sound, with “Share audio” on.");
    if (!caps.mic) return setState(kind, "unsupported", "This browser has no microphone access.");
    if (await granted("microphone")) return start(kind);
    if (s.wanted && !s.stream) setState(kind, "waiting", "Listen to the music through your microphone.");
  }

  // ------------------------------------------------------------------------------------------- streams
  /** Ask the browser. The first call into getDisplayMedia happens synchronously, inside the click. */
  function open(kind, opts) {
    if (kind === "screen")
      return md.getDisplayMedia({
        video: { frameRate: { ideal: 10, max: 15 }, width: { max: 1920 }, height: { max: 1080 } },
        audio: false,
        selfBrowserSurface: "exclude", // not this tab: the studio mirroring itself is a feedback loop
        surfaceSwitching: "include",
      });
    if (kind === "audio") {
      const clean = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };
      if (audioSource(opts) === "system")
        return md
          .getDisplayMedia({ video: true, audio: clean, systemAudio: "include", selfBrowserSurface: "exclude" })
          .then((stream) => {
            if (stream.getAudioTracks().length) return stream;
            for (const t of stream.getTracks()) t.stop();
            const e = new Error("no audio shared");
            e.name = "NoAudioError";
            throw e;
          });
      return md.getUserMedia({ audio: clean, video: false });
    }
    // camera: 0 = the front / default camera; n = the n-th camera, or the back camera on a phone
    const index = Math.max(0, Number(opts && opts.index) || 0);
    const video = { width: { ideal: 320 }, height: { ideal: 240 }, frameRate: { ideal: 15, max: 30 } };
    if (index === 0) return md.getUserMedia({ video: { ...video, facingMode: { ideal: "user" } }, audio: false });
    return md
      .enumerateDevices()
      .catch(() => [])
      .then((all) => {
        const cams = all.filter((d) => d.kind === "videoinput" && d.deviceId);
        const pick = cams[index];
        const v = pick ? { ...video, deviceId: { exact: pick.deviceId } } : { ...video, facingMode: { ideal: "environment" } };
        return md.getUserMedia({ video: v, audio: false });
      });
  }

  function stopTracks(stream) {
    if (stream) for (const t of stream.getTracks()) t.stop();
  }

  function closeStream(kind) {
    const s = S[kind];
    s.token++;
    if (s.stopPump) {
      try {
        s.stopPump();
      } catch (e) {
        /* already gone */
      }
    }
    s.stopPump = null;
    stopTracks(s.stream);
    s.stream = null;
  }

  async function start(kind, override) {
    const s = S[kind];
    if (!s.wanted) return;
    if (override) s.opts = { ...s.opts, ...override };
    closeStream(kind);
    const token = s.token;
    let promise;
    try {
      promise = open(kind, s.opts); // synchronous up to the browser's prompt: keeps the user gesture
    } catch (e) {
      return fail(kind, e);
    }
    setState(kind, "starting", "Waiting for the browser…");
    let stream;
    try {
      stream = await promise;
    } catch (e) {
      if (token === s.token) fail(kind, e);
      return;
    }
    if (token !== s.token || !s.wanted) return stopTracks(stream); // stopped or re-asked meanwhile
    s.stream = stream;
    const ended = () => {
      if (token !== s.token) return;
      closeStream(kind);
      setState(kind, "stopped", kind === "camera" ? "The camera stopped." : "Sharing stopped.");
    };
    for (const t of stream.getTracks()) t.addEventListener("ended", ended);
    try {
      if (kind === "audio") {
        s.source = audioSource(s.opts);
        s.stopPump = pumpAudio(kind, stream, s.source, token);
        const label = s.source === "system" ? "shared sound" : (stream.getAudioTracks()[0] || {}).label || "microphone";
        setState(kind, "live", label);
      } else {
        const track = stream.getVideoTracks()[0];
        s.stopPump = pumpVideo(kind, track, FPS[kind], SIDE[kind], token);
        setState(kind, "live", (track && track.label) || kind);
      }
    } catch (e) {
      closeStream(kind);
      fail(kind, e);
    }
  }

  function fail(kind, e) {
    const name = (e && e.name) || "";
    const what = kind === "camera" ? "camera" : kind === "screen" ? "screen" : "microphone";
    const display = kind === "screen" || (kind === "audio" && audioSource(S[kind].opts) === "system");
    console.info("DeskDot media:", kind, name, e && e.message);
    if (name === "NoAudioError")
      return setState(kind, "error", "No sound was shared. Pick a tab (or, on Windows, the entire screen) and turn on “Share audio”.");
    if (name === "NotAllowedError" || name === "SecurityError" || name === "PermissionDeniedError") {
      if (display) return setState(kind, "stopped", "Nothing was shared. Press the button to choose again.");
      return setState(kind, "denied", `The ${what} is blocked for this site. Allow it from the icon at the left of the address bar (site settings), then try again.`);
    }
    if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError")
      return setState(kind, "error", `No ${what} found.`);
    if (name === "NotReadableError" || name === "TrackStartError" || name === "AbortError")
      return setState(kind, "error", `The ${what} is busy — another app or tab may be using it.`);
    setState(kind, "error", `Couldn't start the ${what}: ${(e && e.message) || e}`);
  }

  // ------------------------------------------------------------------------------------------- frames
  function makeCanvas() {
    if (typeof OffscreenCanvas === "function") return new OffscreenCanvas(1, 1);
    return document.createElement("canvas");
  }

  function framer(kind, side) {
    const canvas = makeCanvas();
    let ctx = null;
    return (source, sw, sh) => {
      if (!sw || !sh) return;
      const k = Math.min(1, side / Math.max(sw, sh));
      const w = Math.max(1, Math.round(sw * k));
      const h = Math.max(1, Math.round(sh * k));
      if (canvas.width !== w || canvas.height !== h || !ctx) {
        canvas.width = w;
        canvas.height = h;
        ctx = canvas.getContext("2d", { willReadFrequently: true, alpha: false });
      }
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(source, 0, 0, w, h);
      const rgba = ctx.getImageData(0, 0, w, h).data;
      const rgb = new Uint8Array(w * h * 3);
      for (let i = 0, j = 0; i < rgba.length; i += 4, j += 3) {
        rgb[j] = rgba[i];
        rgb[j + 1] = rgba[i + 1];
        rgb[j + 2] = rgba[i + 2];
      }
      host.post({ t: "media-frame", kind, w, h, data: rgb.buffer }, [rgb.buffer]);
    };
  }

  function pumpVideo(kind, track, fps, side, token) {
    const send = framer(kind, side);
    const every = 1000 / fps;
    let last = 0;
    const live = () => S[kind].token === token;
    if (typeof window.MediaStreamTrackProcessor === "function") {
      const reader = new window.MediaStreamTrackProcessor({ track }).readable.getReader();
      (async () => {
        while (live()) {
          const { value: frame, done } = await reader.read();
          if (done || !frame) break;
          try {
            const now = performance.now();
            if (live() && now - last >= every) {
              last = now;
              send(frame, frame.displayWidth, frame.displayHeight);
            }
          } catch (e) {
            console.warn("DeskDot media frame", e);
          } finally {
            frame.close(); // a frame left open stalls the camera
          }
        }
      })().catch(() => {});
      return () => reader.cancel().catch(() => {});
    }
    // fallback: a hidden <video> sampled by a timer (throttled to ~1 fps while the tab is in the background)
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = new MediaStream([track]);
    video.play().catch(() => {});
    const timer = setInterval(() => {
      if (!live()) return;
      if (video.readyState >= 2) {
        try {
          send(video, video.videoWidth, video.videoHeight);
        } catch (e) {
          console.warn("DeskDot media frame", e);
        }
      }
    }, every);
    return () => {
      clearInterval(timer);
      video.pause();
      video.srcObject = null;
    };
  }

  // ------------------------------------------------------------------------------------------- sound
  function pumpAudio(kind, stream, source, token) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) throw new Error("no Web Audio in this browser");
    const ac = new AC();
    const src = ac.createMediaStreamSource(stream);
    const node = ac.createScriptProcessor(2048, 1, 1); // 2048 samples ≈ 43 ms at 48 kHz: the desktop's FFT window
    const mute = ac.createGain();
    mute.gain.value = 0; // the node only runs when connected to the output: connect it silently
    node.onaudioprocess = (e) => {
      if (S[kind].token !== token) return;
      const copy = new Float32Array(e.inputBuffer.getChannelData(0));
      host.post({ t: "media-audio", sr: ac.sampleRate, source, data: copy.buffer }, [copy.buffer]);
    };
    src.connect(node);
    node.connect(mute);
    mute.connect(ac.destination);
    ac.resume().catch(() => {});
    // an AudioContext started without any click on the page stays suspended: ask for one
    setTimeout(() => {
      if (S[kind].token === token && ac.state !== "running")
        setState(kind, "waiting", "Click to start listening (the browser needs a click before it plays or records sound).");
    }, 1200);
    return () => {
      node.onaudioprocess = null;
      try {
        src.disconnect();
        node.disconnect();
        mute.disconnect();
      } catch (e) {
        /* already disconnected */
      }
      ac.close().catch(() => {});
    };
  }

  // ------------------------------------------------------------------------------------------- API for the studio
  window.DeskDotMedia = {
    caps,
    snapshot,
    start: (kind, opts) => (S[kind] ? start(kind, opts) : undefined),
    stop(kind) {
      if (!S[kind]) return;
      closeStream(kind);
      if (S[kind].wanted) setState(kind, "stopped", "You stopped sharing.");
      else emit();
    },
  };
  window.addEventListener("pagehide", () => {
    for (const k of Object.keys(S)) closeStream(k);
  });
  host.post({ t: "media-hello" });
  emit();
})();
