import { api } from "../../lib/api";
import { toast, useStore } from "../../lib/store";
import type { LobbyInfo } from "../../lib/types";
import { refreshLobby } from "../Multiplayer";

/** Casino rooms: the same lobby as multiplayer games (`/api/play/lobby`), opened without entering Play mode. */
export async function openCasinoLobby(app: string) {
  try {
    const r = await api.openLobby(app);
    if (r.warning) toast(r.warning, "error");
  } finally {
    await refreshLobby();
  }
}

export async function closeCasinoLobby() {
  useStore.setState({ lobby: null });
  try {
    await api.closeLobby();
  } finally {
    await refreshLobby();
  }
}

/** Hide the join QR on the panel (the room stays open: phones can still join with the code). */
export async function hideCasinoQr() {
  await api.startLobby();
  await refreshLobby();
}

/** Put the join QR back on the panel (the casino app's `lobby` action with the room's address; seats are kept). */
export async function showCasinoQr(app: string, url: string) {
  await api.action(app, "lobby", { url });
  await refreshLobby();
}

/** Move the open room to another casino table: phones keep their seats and wallets (POST /api/play/lobby/switch). */
export async function lobbySwitch(app: string) {
  useStore.setState({ opening: { app, since: performance.now() } });
  const r = await fetch("/api/play/lobby/switch", {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ app }),
  });
  if (!r.ok) {
    // an older engine (no switch): plain activate; the phones must scan the new code
    if (r.status === 404 || r.status === 405) {
      await api.activate(app);
      return;
    }
    let msg = r.statusText;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {
      /* not json */
    }
    toast(String(msg), "error");
    throw new Error(String(msg));
  }
  await refreshLobby();
}

export const lobbyFor = (lobby: LobbyInfo | null, app: string | null) => (lobby && app && lobby.app === app ? lobby : null);
