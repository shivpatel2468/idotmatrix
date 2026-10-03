// Dev/test aid (not shipped): a fake Web Bluetooth iDotMatrix panel for headless browsers (docs/WEB_APP.md).
// Inject it before the page loads (Playwright: `page.addInitScript({ path })`). It records every GATT write in
// `window.__bleWrites`, refuses packets longer than 244 bytes (like a small-MTU link, to exercise the step-down),
// acks every burst of writes on fa03, and `window.__mockDevice.gatt.disconnect()` simulates a link loss.
(() => {
  const writes = [];
  window.__bleWrites = writes;
  class Char extends EventTarget {
    constructor(uuid) {
      super();
      this.uuid = uuid;
      this.value = null;
    }
    async writeValueWithoutResponse(d) {
      const u8 = new Uint8Array(d.buffer ? d.buffer.slice(d.byteOffset, d.byteOffset + d.byteLength) : d);
      if (!device.gatt.connected) throw new DOMException("GATT Server is disconnected.", "NetworkError");
      if (u8.length > 244) throw new DOMException("Value too long", "NotSupportedError");
      writes.push({ t: performance.now(), n: u8.length, head: Array.from(u8.slice(0, 5)) });
      // like the panel: an ack on fa03 shortly after a message (GIF chunks and images are acked)
      clearTimeout(this._ack);
      this._ack = setTimeout(() => window.__notify && window.__notify([5, 0, 1, 0, 1]), 40);
    }
    writeValueWithResponse(d) {
      return this.writeValueWithoutResponse(d);
    }
    async startNotifications() {
      window.__notify = (bytes) => {
        this.value = new DataView(new Uint8Array(bytes).buffer);
        this.dispatchEvent(new Event("characteristicvaluechanged"));
      };
      return this;
    }
  }
  const chars = {
    "0000fa02-0000-1000-8000-00805f9b34fb": new Char("fa02"),
    "0000fa03-0000-1000-8000-00805f9b34fb": new Char("fa03"),
  };
  const service = { getCharacteristic: async (u) => chars[u] };
  const device = new EventTarget();
  device.id = "mock-panel-1";
  device.name = "IDM-MOCK01";
  device.gatt = {
    connected: false,
    async connect() {
      await new Promise((r) => setTimeout(r, 50));
      this.connected = true;
      return { getPrimaryService: async () => service };
    },
    disconnect() {
      if (!this.connected) return;
      this.connected = false;
      device.dispatchEvent(new Event("gattserverdisconnected"));
    },
  };
  window.__mockDevice = device;
  Object.defineProperty(navigator, "bluetooth", {
    configurable: true,
    value: {
      getAvailability: async () => true,
      getDevices: async () => [],
      requestDevice: async () => device,
    },
  });
})();
