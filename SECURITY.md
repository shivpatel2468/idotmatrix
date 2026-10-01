# Security

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Use GitHub's private reporting instead:
**Security → Report a vulnerability** on this repository. You'll get a reply within a few days.

Helpful details: what you found, how to reproduce it, and what an attacker could do with it.

## How DotDeck is designed to be safe

- **Local-first, no accounts, no telemetry.** The engine runs on your own computer, Pi or phone.
- **LAN-closed by default.** The engine listens on your network only so friends' phones can join games:
  other devices can reach **only** the game-controller pages (`/p/…`, `/ws/p/…`, behind random room codes). The
  studio and the API stay local unless you set `lan_studio = true` (which has no login: only do that on a network
  you trust).
- **Secrets stay on your machine.** Tokens and passwords you type into the studio are stored only in
  `data/state.json` (git-ignored). They are masked as `••••••` in every API response and snapshot, never logged,
  and never sent anywhere except the service they belong to.
- **Never commit `dotdeck.toml`, `.env*` or `data/`.** The repo's `.gitignore` excludes them; please keep it that way
  in forks and pull requests.
- **One Bluetooth owner.** Only the engine talks to the panel; everything else goes through the HTTP API.

## Supported versions

Only the latest `main` gets fixes.
