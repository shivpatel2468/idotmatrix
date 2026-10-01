/** Short, useful tips shown while things load — each teaches one thing people rarely discover alone. */
export const TIPS = [
  "Press Ctrl K anywhere to open the command palette — jump to any app or action.",
  "Drop any image or GIF onto the studio to put it on the panel. Photos are LED-calibrated automatically.",
  "Text Studio: click anywhere on the preview to place text, then drag it around.",
  "Autopilot (Settings → Playlist & hand-off) makes the panel follow the app you're using — Spotify in front? Lyrics appear.",
  "Games play themselves. Press the arrow keys or WASD to take over; Space is the action button.",
  "Pets dance to music. Turn on Music sync and pick system audio or your microphone in Settings → Device → Sound input.",
  "Run the colour calibration wizard (Settings → Display & colour) — five questions tune whites, blacks and gamma.",
  "Drag the dividers between the panels to give the display more room, and tap a preset in the playback bar to rotate a whole category.",
  "Star apps in the library to keep your favourites at the top.",
  "Notifications from Teams, WhatsApp, Discord and more can appear on the panel — Settings → Notifications & integrations.",
  "Flight Radar: click a blip on the preview to see the flight's route, altitude and speed.",
  "Screen Mirror → Around cursor + the magnification slider turns the panel into a live magnifier.",
  "Set your favourite team in Live Scores and you'll get a goal celebration even when it's not on screen.",
  "The eject-seat guard protects the display power switch — lift the cover, then press the red button.",
  "Everything is scriptable: POST /api/notify from any script or CI job to flash a message.",
  "Claude can drive your panel over MCP — ask it to draw pixel art and check the snapshot.",
  "Set the display refresh rate (Hz) and night mode in Settings → Display & colour.",
  "Font Lab renders your own pixel TTF fonts — drop .ttf files into data/fonts.",
  "Pet World: characters live in a little world, doing jobs, playing football and sleeping at night.",
  "Double-click any app in the library to show it instantly.",
];

export const randomTip = (seed = Math.random()) => TIPS[Math.floor(seed * TIPS.length) % TIPS.length];
