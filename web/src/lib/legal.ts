/**
 * Legal copy and links shared by the studio (Settings → About, the casino age gate). One place for the contact
 * address and the page links, so the website (scripts/site_legal.py) and the studio stay in step.
 */

/** Filled in before deploying (the website's generator has its own copy in scripts/site_legal.py). */
export const CONTACT_EMAIL = "shiv.patel1.3.2003@gmail.com";

export const OWNER = "Shiv Patel";

/** Pages on the website (absolute: the studio runs at /app/ on the same origin). */
export const LEGAL_LINKS: { href: string; label: string }[] = [
  { href: "/privacy.html", label: "Privacy" },
  { href: "/terms.html", label: "Terms" },
  { href: "/licenses.html", label: "Open-source licences" },
  { href: "/license.html", label: "DeskDot licence" },
];

export const UNOFFICIAL_LINE =
  "DeskDot is an independent product by Shiv Patel, India. Unofficial: not made, endorsed or supported by Shenzhen Heaton Technology Co., Ltd. or the iDotMatrix brand. “iDotMatrix” is a trademark of its owner and is used only to describe compatible panels. All other trademarks belong to their owners.";

export const LICENCE_LINE =
  "DeskDot versions up to v3.2 were published under the MIT licence and remain so. Future versions will be proprietary software licensed under the DeskDot EULA.";

// ------------------------------------------------------------------ casino age gate (legal review L4)
/** Bump the key when the gate's copy changes: everyone is asked again. */
export const CASINO_GATE_KEY = "deskdot.casino.agegate.v1";
const CASINO_GATE_DECLINED = "deskdot.casino.agegate.declined";

export function casinoGateAccepted(): boolean {
  try {
    return localStorage.getItem(CASINO_GATE_KEY) === "accepted";
  } catch {
    return false;
  }
}

export function acceptCasinoGate() {
  try {
    localStorage.setItem(CASINO_GATE_KEY, "accepted");
    sessionStorage.removeItem(CASINO_GATE_DECLINED);
  } catch {
    /* private mode: asked again next time */
  }
}

/** Declined: remembered for this browser session (a new casino table doesn't pull the studio back in). */
export function declineCasinoGate() {
  try {
    sessionStorage.setItem(CASINO_GATE_DECLINED, "1");
  } catch {
    /* private mode */
  }
}

export function casinoGateDeclined(): boolean {
  try {
    return sessionStorage.getItem(CASINO_GATE_DECLINED) === "1";
  } catch {
    return false;
  }
}

export function clearCasinoGateDecline() {
  try {
    sessionStorage.removeItem(CASINO_GATE_DECLINED);
  } catch {
    /* private mode */
  }
}

export const CASINO_GATE = {
  title: "Play-money casino · 18+ only",
  accept: "I'm 18+ · play for fun",
  leave: "Leave the casino",
} as const;

export const PLAY_MONEY_LINE = "Play money only · credits have no value · 18+ · just for fun";
