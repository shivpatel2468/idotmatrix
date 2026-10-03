/* DeskDot web app — the engine worker (docs/WEB_APP.md).
 *
 * Runs the real Python engine (src/deskdot) under Pyodide, off the page's main thread so rendering never janks the
 * studio and background-tab timer throttling doesn't stall the panel. The page talks to it with postMessage:
 *
 *   page → worker   {t:"http", id, method, path, headers, body}      → {t:"http", id, status, headers, body}
 *                   {t:"ws-open", sid, path} {t:"ws-send", sid, data} {t:"ws-close", sid}
 *                   {t:"ble-ev", ev, args}   (Web Bluetooth events from the page)   {t:"ble-picked"}  {t:"sync"}
 *   worker → page   {t:"status", phase, detail, pct} {t:"ready"} {t:"fatal", error}
 *                   {t:"ws", sid, ev, data}  {t:"ble", op, ...}  (GATT requests for the page to perform)
 *
 * The panel's GATT session lives on the page (navigator.bluetooth doesn't exist in workers); `deskdotBle` below is
 * the bridge device/web.py drives — same contract as the Android app's Kotlin BleBridge.
 */
"use strict";

const BASE = new URL("../", self.location.href); // …/app/
let manifest = null;
let pyodide = null;
let web = null; // the deskdot.web_main module (PyProxy)
let ready = false;
const early = []; // messages that arrived before the engine was ready

function post(msg, transfer) {
  self.postMessage(msg, transfer || []);
}
function status(phase, detail, pct) {
  if (phase !== "packages") console.info(`[deskdot] ${phase} at ${Math.round(performance.now())} ms`);
  post({ t: "status", phase, detail: detail || "", pct: pct == null ? null : pct });
}

// ------------------------------------------------------------------------------------------- BLE bridge (→ page)
let bleListener = null; // a PyProxy of device/web.py's _Listener (create_proxy: lives for the session)
const bleCall = (name, ...args) => {
  if (!bleListener) return;
  try {
    bleListener[name](...args);
  } catch (e) {
    console.error("ble listener", name, e);
  }
};
self.deskdotBle = {
  connect(namePrefix, listener) {
    bleListener = listener;
    post({ t: "ble", op: "connect", namePrefix });
  },
  write(data, withResponse, token) {
    const copy = new Uint8Array(data); // detach from the wasm heap before transferring
    post({ t: "ble", op: "write", data: copy, withResponse: !!withResponse, token }, [copy.buffer]);
  },
  disconnect() {
    post({ t: "ble", op: "disconnect" });
  },
};

// ------------------------------------------------------------------------------------------- persistence
let syncing = false;
let syncAgain = false;
let syncTimer = 0;
function syncSoon() {
  if (syncTimer) return;
  syncTimer = setTimeout(() => {
    syncTimer = 0;
    syncNow();
  }, 250);
}
function syncNow() {
  if (!pyodide) return;
  if (syncing) {
    syncAgain = true;
    return;
  }
  syncing = true;
  pyodide.FS.syncfs(false, (err) => {
    syncing = false;
    if (err) console.warn("DeskDot: saving to IndexedDB failed", err);
    if (syncAgain) {
      syncAgain = false;
      syncNow();
    }
  });
}

// ------------------------------------------------------------------------------------------- boot
async function boot() {
  status("manifest", "Checking for updates");
  manifest = await (await fetch(new URL("engine/manifest.json", BASE), { cache: "no-cache" })).json();
  const indexURL = manifest.pyodide.indexURL;
  // the engine archive downloads while Python starts
  const zipping = fetch(new URL("engine/" + manifest.engine, BASE)).then((r) => {
    if (!r.ok) throw new Error(`engine archive: HTTP ${r.status}`);
    return r.arrayBuffer();
  });

  status("runtime", `Downloading Python ${manifest.pyodide.python} (Pyodide ${manifest.pyodide.version})`, 5);
  importScripts(indexURL + "pyodide.js");
  pyodide = await self.loadPyodide({
    indexURL,
    // the engine never needs stdin; print() goes to the console
    stdout: (s) => console.log(s),
    stderr: (s) => console.warn(s),
  });

  status("packages", "Loading numpy, Pillow, pydantic, FastAPI", 35);
  let done = 0;
  const wanted = manifest.packages.length + manifest.wheels.length;
  await pyodide.loadPackage(manifest.packages, {
    messageCallback: (m) => {
      if (/^Loaded /.test(m)) status("packages", m.replace(/^Loaded /, "Loaded "), 35 + Math.min(40, (++done / wanted) * 40));
    },
    errorCallback: (m) => console.warn(m),
  });
  for (const w of manifest.wheels) await pyodide.loadPackage(new URL("engine/" + w, BASE).href);

  status("engine", "Unpacking the DeskDot engine", 78);
  const zip = await zipping;
  const site = pyodide.runPython("import sysconfig; sysconfig.get_paths()['purelib']");
  pyodide.unpackArchive(zip, "zip", { extractDir: site });

  status("storage", "Restoring your settings", 84);
  const FS = pyodide.FS;
  FS.mkdirTree("/deskdot");
  FS.mount(FS.filesystems.IDBFS, {}, "/deskdot");
  await new Promise((res) => FS.syncfs(true, (err) => (err && console.warn("restore", err), res())));

  status("start", "Starting the engine", 90);
  web = pyodide.pyimport("deskdot.web_main");
  await web.boot("/deskdot", syncSoon, manifest.proxy || null);
  setInterval(syncNow, 15000); // media uploads and app data saved outside the state file

  ready = true;
  status("ready", "Engine running", 100);
  post({ t: "ready", version: manifest.version });
  while (early.length) handle(early.shift());
}

// ------------------------------------------------------------------------------------------- page messages
const sockets = new Map();

async function http(msg) {
  try {
    // http_js converts its result with to_js: a plain object {status, headers, body: Uint8Array}
    const res = await web.http_js(msg.method, msg.path, msg.headers || [], msg.body ? new Uint8Array(msg.body) : null);
    const body = res.body instanceof Uint8Array ? res.body.slice() : new Uint8Array(0);
    post({ t: "http", id: msg.id, status: res.status, headers: res.headers, body: body.buffer }, [body.buffer]);
  } catch (e) {
    post({ t: "http", id: msg.id, status: 500, headers: [["content-type", "text/plain"]], body: null, error: String(e) });
  }
}

function handle(msg) {
  switch (msg.t) {
    case "http":
      return http(msg);
    case "ws-open": {
      const emit = (ev, data) => {
        let payload = data;
        let transfer = [];
        if (data instanceof Uint8Array) {
          // web_main converts bytes with to_js (a fresh copy), so its buffer can be handed over
          payload = data.byteOffset === 0 && data.buffer.byteLength === data.byteLength ? data.buffer : data.slice().buffer;
          transfer = [payload];
        }
        post({ t: "ws", sid: msg.sid, ev, data: payload }, transfer);
      };
      sockets.set(msg.sid, emit);
      return web.ws_open(msg.sid, msg.path, emit);
    }
    case "ws-send":
      return web.ws_send(msg.sid, typeof msg.data === "string" ? msg.data : new Uint8Array(msg.data));
    case "ws-close":
      return web.ws_close(msg.sid, msg.code || 1000);
    case "ble-ev":
      return bleCall(msg.ev, ...(msg.args || []));
    case "ble-picked":
      if (bleListener) bleCall("onUserPicked");
      else web.user_picked();
      return;
    case "sync":
      return syncNow();
  }
}

self.onmessage = (e) => {
  const msg = e.data;
  if (msg.t === "sync") return syncNow();
  if (!ready) {
    // BLE events can't wait (a connect may be pending), but nothing BLE happens before the engine runs
    early.push(msg);
    return;
  }
  handle(msg);
};

boot().catch((e) => {
  console.error(e);
  post({ t: "fatal", error: String((e && e.message) || e) });
});
