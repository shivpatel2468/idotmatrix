import { pushFrame, useStore } from "./store";

let sock: WebSocket | null = null;
let retry = 0;

/** One WebSocket for the whole studio: JSON state + binary 3072-byte RGB frames. Reconnects forever. */
export function connect() {
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";
  sock = ws;
  useStore.setState({ link: "connecting" });

  ws.onopen = () => {
    retry = 0;
    useStore.setState({ link: "open" });
  };
  ws.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) {
      pushFrame(new Uint8Array(ev.data));
      return;
    }
    const msg = JSON.parse(ev.data as string);
    if (msg.type === "state") useStore.setState({ state: msg.state, stateAt: performance.now() });
  };
  ws.onclose = () => {
    sock = null;
    useStore.setState({ link: "closed" });
    const delay = Math.min(8000, 400 * 2 ** retry++);
    setTimeout(connect, delay);
  };
}

/**
 * Game controls (Snake…) go straight to the app over the socket. `player` > 1 is an extra local player on this
 * computer (the other half of the keyboard, a second gamepad): the engine seats them on their first press.
 */
export function sendInput(app: string, key: string, player = 1) {
  if (sock?.readyState !== WebSocket.OPEN) return;
  sock.send(JSON.stringify(player > 1 ? { type: "input", app, key, player } : { type: "input", app, key }));
}

/** Low-latency canvas strokes go over the socket instead of REST. */
export function paint(pixels: [number, number, string][]) {
  if (sock?.readyState === WebSocket.OPEN && pixels.length) {
    sock.send(JSON.stringify({ type: "paint", pixels }));
  }
}
