# What's new in DeskDot

Every update in plain words: what it was like before, and what changed. (The detailed technical log for developers
is in [CHANGELOG.md](CHANGELOG.md).)

<!-- Format (the website's "What's new" page is built from this file — keep it):
## <version> — <d Mon yyyy> · <one-line headline>
### New | Better | Fixed
- **<title>**
  - Before: <one sentence>
  - Now: <one or two sentences>
-->

## 3.8.0 — 29 Oct 2026 · Install DeskDot like any app, and update it from inside

### New

- **Installers for Windows, Mac and Android**
  - Before: to use DeskDot you had to download the code, install Python tools and type commands in a terminal.
  - Now: download one file from GitHub — a setup program for Windows, a disk image for Mac, an app for Android —
    and install it like any other app. DeskDot opens the studio in your browser and sits in the tray, ready to go.
- **Updates from inside DeskDot**
  - Before: to get a new version you had to go to GitHub, download it and set it up again yourself.
  - Now: when a new version is out, a small "Update available" sign appears at the top. Settings → Device →
    Updates shows what's new in plain words, and one button downloads it, checks it's genuine and installs it.
    On a computer DeskDot restarts by itself; on Android the phone asks you to confirm. Your settings stay.
- **You choose whether DeskDot looks for updates**
  - Before: there was nothing to check.
  - Now: about every 6 hours DeskDot asks GitHub if there's a new version. Nothing about you is sent. Turn it off
    in Settings → Device → Updates, or press Check now whenever you like.
- **Start DeskDot when you sign in (Windows)**
  - Before: you had to start DeskDot yourself every time.
  - Now: tick one box in the installer (or "Start with login" in the tray menu) and it starts with Windows.

### Better

- **Your settings live in one safe place**
  - Before: settings and data sat inside the DeskDot folder, next to the program.
  - Now: the installed app keeps them in your own user folder, so updating or reinstalling never touches them.

## 3.7.0 — 12 Oct 2026 · Page themes everywhere and a luxury casino on the TV

### New

- **Page themes for the whole studio**
  - Before: the studio only had its one look (ember in the dark, rose in the light); only the casino tables had themes.
  - Now: pick one of 21 page themes — like Royal blue, Galaxy, Sakura night, Glacier or Citrus — in Settings → Display
    & colour, the Display menu or the phone's Quick controls. Every page, the phone app and the launcher change colour
    together, in light and dark mode, with a smooth fade. It's saved on your computer, so every device you use shows
    the same theme. The casino keeps its own table themes.
- **Apps match the page theme**
  - Before: clocks, dashboards and text apps on the panel always used their own fixed colours.
  - Now: they take the page theme's colours too, just like casino games take their table's colours — tuned so they
    stay bright and readable on the LEDs. Any colour you chose yourself stays, photos, flags, weather icons and games
    keep theirs, and each app has a "Follow page theme" switch if you'd rather it didn't.

- **A luxury casino on the TV**
  - Before: the TV showed the casino table flat, with a simple list of players on the side.
  - Now: every table looks like a real high-limit table in a private salon — polished wood rails with brass, deep
    felt under a warm lamp, gold-leaf lettering — and the players sit in a gallery of leather name plates with their
    picture, their chips on the table and their money. It works with or without the LED panel.
- **You can see who won**
  - Before: when a round ended it was hard to tell who had won.
  - Now: a big arcade moment plays on the TV — WINNER!, BIG WIN!, MEGA WIN! or JACKPOT! slams onto the screen, gold
    coins fly into the winner's name plate, which lights up while "+12,500" counts up, and the screen shakes on big
    wins. Losing chips get swept away with a red "−500", and when nobody wins it says HOUSE WINS. Every TV and phone
    plays it at the same moment.
- **Your own win on your phone**
  - Before: your phone showed a small "You won" card.
  - Now: your phone shows the same JACKPOT / MEGA WIN / BIG WIN moment for your own result, with spinning rays, a
    counter, a coin shower and a buzz pattern.
- **Choose the roulette dolly**
  - Before: the marker on the winning number was always a glass dolly.
  - Now: pick one of eight in the casino's House settings — Classic Gold (the default), Crystal, Chrome, Black Onyx &
    Gold, Rose Gold, Diamond-cut, Marble & Brass or Neon Arcade. On the TV the dealer's hand lifts it, glides it over
    the table and sets it down on the number with a soft click.
- **Chips that match the table**
  - Before: every table used the same chips.
  - Now: each table theme has its own chip design — clay, printed ceramic, gold-rimmed, neon, jade, pixel or ivory —
    on the TV, the phones and the studio. The colours that tell you a chip's value stay the same. You can also pick
    one set for every table in House settings.
- **Money that rolls like a slot machine**
  - Before: credits just changed to the new number.
  - Now: when your credits change, the digits spin like slot-machine reels and land on the new amount — on the TV,
    your phone and the studio.

- **Eight new Now Playing looks**
  - Before: Now Playing had 11 layouts.
  - Now: 19. New ones: a cassette whose reels turn and whose tape moves from one reel to the other as the song
    plays, twin VU meters with needles that swing to the music (or LED ladders), a CD with the cover printed on it
    and a rainbow shine, an old radio dial whose needle sweeps to a new station for every song, the cover as a
    tile mosaic that builds itself tile by tile, a scrolling waveform, the song name huge, and Word pop — the
    lyrics one big word at a time, right on the beat.
- **Pick a layout by its picture**
  - Before: you chose the Now Playing layout from a list of names.
  - Now: while Now Playing is on the panel, the full-screen view shows a small picture of every layout. Tap one to
    switch. The song, the artist and the cover are shown there too, with previous, play/pause and next buttons.

### Better

- **Goal alerts off by default**
  - Before: every time a team scored, a celebration took over the panel, even when you were showing something else.
  - Now: goal and score alerts start switched off. Turn them on in Live Scores → Alerts if you want them.
- **More movement at the TV table**
  - Before: the roulette ball and the cards moved simply.
  - Now: the ball streaks as it races round and hops over the frets, the camera zooms in on the winning pocket and
    then on the number, cards turn over in 3D, dice tumble and slot reels blur — all still in step with the panel
    and every phone.

- **A daylight casino on the TV**
  - Before: Light mode on the TV left a casino table dark, and only a few small parts changed.
  - Now: Light turns the whole TV into an ivory and champagne salon — a white-lacquer rail with gold inlay, ivory
    seat plaques, a light header and panel frame. The felt keeps the table's colour, and switching fades smoothly.
- **The DeskDot logo in the middle of the TV header**
  - Before: the logo sat in the corner and kept flickering, so it often looked half-lit.
  - Now: the logo sits in the centre, lights up once and stays lit. The game is on the left and the clock on the
    right.
- **Nicer, easier-to-read type on the TV**
  - Before: the TV used plain system fonts in mixed styles.
  - Now: names and titles use an elegant serif, and everything else uses the studio's own font with even-width
    numbers. All of it is easy to read from across the room.
- **Pick the roulette dolly and chips from the TV**
  - Before: you could only change the dolly and the chip design deep in the studio, and many people never found them.
  - Now: at a casino table, the TV's menu has Dolly and Chips rows showing the real styles. A pick changes every
    screen. In the studio they now sit at the top of Casino → House.
- **Casino table colours in light mode**
  - Before: in light mode the casino looked pale grey whatever table you picked — the side panels, the chip set
    and dolly cards and the buttons barely showed the table's colours.
  - Now: the whole casino screen takes the table's colours in light mode too, on the computer and on phones. The
    side panels, cards, buttons, player rows and chip tray are washed in the felt's colour with the accent glowing
    along the edges, the picked card has a clear coloured ring, and the chip sets and dollies sit on a little piece
    of the table's felt. Dark tables like Cyber grid or Riviera noir get a light steel room lit by their accent,
    and tables with ivory or champagne trim get buttons in the felt's colour. Text stays easy to read, and dark mode
    looks the same as before.
- **The panel preview turns light in light mode**
  - Before: in light mode the picture of the panel in the middle of the studio — and every app picture in the
    library — stayed a black screen with glowing colours, which looked out of place on the white page.
  - Now: in light mode the preview becomes a light "paper" panel, like ink on porcelain: white turns into near-black,
    black into the light background, and every colour is re-tuned so it stays easy to read — yellow becomes a deep
    gold, cyan a teal, red and blue stay rich. Dim parts stay lighter than bright ones, so text never melts into the
    background. Every app, the library pictures, the casino games and the launcher follow, and switching fades
    smoothly. Only the screen changes — the real panel looks exactly the same. Prefer the black panel? Pick "Dark
    device" under *Panel preview in light mode* in the Display menu (the gear).
- **A light DeskDot logo in light mode**
  - Before: in light mode the logo in the header sat on a small black sign so its glowing letters would show.
  - Now: the logo has its own light version — the same letters, built and lit the same way, in deep rose and gold
    dots, straight on the header like the glowing one in dark mode. The phone pages, the web app and the TV show it
    too when they are in light mode.
- **Liquid Glass everywhere**
  - Before: bars, menus, sheets and buttons were solid painted surfaces.
  - Now: the top bar, the phone's tab bar (now a floating capsule), sheets, menus, pop-ups, the playback dock and the
    panels around the LED panel are made of glass in the style of Apple's Liquid Glass — they blur and gently bend
    what's behind them, catch the light along their edges (the highlight follows your mouse, or the tilt of your
    phone), and buttons, switches, sliders and tabs squash and spring back when you press them. It works in light
    and dark and in every page theme, on the phone pages, the web app and the launcher too; the TV gets a calm,
    still version.
  - On older or slower phones, inside the Android app, and wherever blur isn't supported, the glass turns frosted —
    nearly solid, so text never sits on top of busy content. "Reduce transparency" on your device makes it solid. You
    can choose for yourself in the Display menu → More → Glass (Auto, Clear, Frosted, Solid).

### Fixed

- **TV menu buttons did nothing**
  - Before: clicking or tapping Pixel, LED, Glow or Auto, HQ, Lite in the TV menu did nothing.
  - Now: every option works with a mouse, a tap, the keyboard or a TV remote, and it lights up when you pick it.
- **Unreadable TV menu in light mode**
  - Before: at a casino table in light mode, the menu's titles were pale on a pale card.
  - Now: the text is dark on the light card (and light on the dark one) and easy to read.

- **Now Playing has many more options**
  - Before: you could only change the layout, the colours and a few lyric settings.
  - Now: the songs can slide, dissolve or zoom into each other; the layouts can change on every song or every few
    seconds; you choose what happens when you pause (dim, a pause sign, freeze the picture or switch to the idle
    screen) and what shows when nothing plays (now also recent covers, calm waves or a sleepy "silence" screen).
    Covers can be pixelated, posterised or dithered, with your own contrast and colour. Long titles can loop,
    bounce or show a few words at a time; the album and a small sign for where the music plays (music app,
    browser or player — never a brand logo) can be shown. Lyrics get a translation line when the lyrics have one,
    a choice of line spacing and three highlight styles.
- **Music buttons only when they work**
  - Before: previous, play/pause and next always showed, even when the computer couldn't control the player.
  - Now: they work on Windows, on macOS (Spotify and Music, other players with nowplaying-cli) and on Linux
    (playerctl), and they hide where the player can't be controlled.
- **No more black patches in light mode**
  - Before: light mode still had black bits: black badges and play buttons on the app tiles, the black frame and
    screws around the LED panel in the casino and the fruit-fly view, black Now Playing layout pictures, a black AI
    preview, dark tooltips, dark brown dimming behind dialogs, a black-and-yellow power guard, a dark band across the
    casino side panels, and black panels and plaques on the phone casino page, the phone controller and the TV.
  - Now: all of them are light — glass badges, white enamel around the panel, the panel drawn in ink on porcelain
    everywhere (also on the TV and the phone pages), a pale frosted veil behind dialogs. The only dark things left
    are the ones you choose (the "Dark device" panel preview), the fruit fly's 3D scenes, and real colours of the
    games (black roulette pockets, black chips, cards).
- **No box around the logo**
  - Before: the DeskDot logo in the middle of the header sat inside a little plate or sign.
  - Now: the logo sits straight on the header, in the studio, the phone app, the TV, the phone pages and the web app.
- **Phone tab bar sometimes off screen**
  - Before: on some phones the page came out a little too wide, so it zoomed out and the tab bar slipped below the
    bottom edge.
  - Now: the page fits the screen exactly and the tab bar is always there.

## 3.6.0 — 9 Oct 2026 · Light mode, a better phone app, 14 new live apps

### New

- **Light mode**
  - Before: DeskDot only came in dark.
  - Now: a premium light look — warm ivory, deep rose and champagne gold — for the studio, the phone app, the
    phone pages and the TV, with paper-like texture, soft depth and gold-leaf details as rich as dark mode. Pick Light,
    Dark or Auto (follows your device) in Settings → Display & colour.
- **Light / dark button on phones**
  - Before: you had to dig into Settings to change the look.
  - Now: a small round button in the bottom-left corner switches light and dark with one tap (hold it for Auto). The
    phone's own top and bottom bars change colour too.
- **A luxury casino**
  - Before: the casino rooms were plain and dark only.
  - Now: gold-framed tables, engraved headings, embossed chips and an ivory "salon" in light mode — and all 21 table
    themes look right in both light and dark.
- **Choose the app's icon**
  - Before: the phone app had one icon.
  - Now: pick from seven icon designs in Settings → Display & colour → App icon.
- **Apps right under the panel**
  - Before: the phone's Panel screen showed only the panel; apps were on another tab.
  - Now: swipe rows of your favourite, recent and other apps sit right under the panel — tap one to show it.
- **Connection panel**
  - Before: when the panel wasn't connected it was hard to tell where it was connected or how to fix it.
  - Now: tap the status at the top to see what's connected and where, with one button to reconnect or move the
    panel to this tab, and plain-language help when something's wrong.
- **TV options from the remote**
  - Before: changing the TV's look meant editing its web address.
  - Now: press OK on the remote to pick the panel look (Pixel, LED or Glow), the quality and light or dark — or set
    every TV at once from the studio's Show on TV panel.

- **Aurora Watch**
  - Before: there was no way to know if the northern (or southern) lights might show up.
  - Now: see how stormy space weather is right now on a 0–9 scale, the forecast for the next day, a world map with
    the glowing aurora ring, and your own chance of seeing it. It can alert you when a storm starts.
- **Bitcoin Network**
  - Before: only the Bitcoin price was available.
  - Now: see what it costs to send Bitcoin right now, how long ago the last block was found, and how many days are
    left until the next "halving".
- **Crypto Market**
  - Before: you could follow single coins, but not the market as a whole.
  - Now: the total value of all coins, how much of it is Bitcoin, the day's biggest winners and losers, and the
    "fear and greed" mood score.
- **Race Countdown**
  - Before: you had to look up when the next Grand Prix starts.
  - Now: a countdown to the next race with the time of the next session in your time zone, LIVE during the race,
    and the top three afterwards.
- **Long Weekend**
  - Before: Holidays counted down to the next public holiday only.
  - Now: count down to the next long weekend, see how many days off it gives, and whether one extra day off would
    make it longer.
- **Bike Share**
  - Before: nothing for getting around town.
  - Now: free bikes and empty docks at the bike-share stations closest to you, in more than 700 cities.
- **Earth Events**
  - Before: Earthquakes was the only "what is happening on Earth" app.
  - Now: wildfires, storms, volcanoes and sea ice happening right now, as blinking dots on a world map, with the
    newest one named underneath.
- **World Flags**
  - Before: no app about countries.
  - Now: a flag of the day, a shuffle of every country's flag, or a quiz where the name appears after a pause.
- **Rain Chance**
  - Before: Weather showed the day, not hour by hour.
  - Now: the chance of rain for each of the next 12 hours and when it is highest — umbrella or not.
- **Wind Compass**
  - Before: wind speed was a small number on the Weather screen.
  - Now: a compass shows where the wind is blowing, how strong it is and the gusts, plus the next 12 hours.
- **Wiki Trending**
  - Before: no way to see what everyone is reading about.
  - Now: yesterday's most-read Wikipedia articles, one by one, with how many people read them and a small chart
    that shows a sudden spike.
- **Asteroid Flyby**
  - Before: nothing about space rocks.
  - Now: the next asteroid to pass close to Earth — when, how close compared with the Moon, how big and how fast.
    These passes are routine and harmless.
- **Game Server**
  - Before: you had to open the game to see who is playing.
  - Now: type your block-game server's address and see whether it is online, how many players are on, its icon and
    its message.
- **TV Tonight**
  - Before: no TV guide.
  - Now: what is on TV now and later tonight in your country, two shows at a time.
- **Picture of the day in Photo Frame**
  - Before: Photo Frame showed museum art, nature photos and animals.
  - Now: it can also show Wikimedia's picture of the day from the last week.

### Better

- **Smoother phone app**
  - Before: the app ran at 60 frames a second with occasional stutter.
  - Now: it asks for your screen's full speed (up to 120 Hz) and heavy effects that caused stutter are gone.
- **Simpler display settings**
  - Before: the gear opened a long page with everything about the screen in one place.
  - Now: it opens a small menu with three picture tiles (Glow, Pixel, LED), one slider, and the rest under "More".
- **Richer icons, presets and menus**
  - Before: plain icons, plain preset cards and small dropdowns.
  - Now: detailed two-tone icons, preset cards with artwork and a big play button, and pickers that slide up from
    the bottom on phones.
- **Lite mode on the TV looks the same**
  - Before: Lite made the TV smoother by dropping glows and sharpness.
  - Now: Lite looks exactly like the full mode; both were made faster instead.

- **A health check for every data source**
  - Before: when a free data source changed or shut down, an app simply went quiet until someone noticed.
  - Now: one command checks all 100+ sources DeskDot uses — whether they answer, how fast, and whether the answer
    still looks the way the apps expect — and writes a report.

### Fixed

- **Phone app black screen**
  - Before: if the app opened before DeskDot had started on the phone, it could stay on a black screen.
  - Now: it waits and loads by itself, and after an update it never shows the old version.
- **See-through bars on phones**
  - Before: apps showed through the search bar, the section titles and the bottom tab bar.
  - Now: those bars are solid.
- **Museum art in Photo Frame**
  - Before: since 1 October, art from The Met stopped loading because the museum changed its search.
  - Now: it uses the museum's new search and loads again.
- **Stocks when the main source fails**
  - Before: the backup source had shut down, so a hiccup at the main source left prices blank.
  - Now: a new backup source fills in for US stocks and funds.
- **Flight Radar backup**
  - Before: one of the backup flight sources started refusing requests.
  - Now: it is replaced by another free source, so planes keep showing when the main source is busy.
- **Hacker News headlines in some countries**
  - Before: some internet providers block the Hacker News feed, so Headlines showed OFFLINE.
  - Now: it switches to another copy of the same feed by itself.
- **Crypto Ticker in the USA**
  - Before: the price source refuses visitors from the USA, so the ticker stayed empty there.
  - Now: it switches to the same prices from a mirror that works everywhere.

## 3.5.0 — 7 Oct 2026 · Housie, the TV view and a high-roller casino

### New

- **Housie (Tambola)**
  - Before: the casino had nine tables and no number game.
  - Now: a tenth table — buy tickets, the caller draws 1 to 90, your phone marks the numbers and you claim Early
    Five, the lines, Four Corners or Full House. The house checks every claim.
- **Penguin Escape**
  - Before: there was no puzzle game made for the panel.
  - Now: help a penguin slide across the ice and out of the zoo in 16 levels — push ice blocks, find keys, collect
    fish and stay out of the keepers' torch light.
- **TV view**
  - Before: only the small LED panel showed the game; everyone had to crowd around it.
  - Now: open the game on any TV, projector or tablet browser in full HD. Casino tables are drawn in full with every
    player's chips, and the TV shows the same spin, cards and result as the panel at the same moment. Press the gold
    TV button under the panel to get the link.
- **Chips for high-roller tables**
  - Before: the chip rack was always 1, 5, 25, 100 and 500, even when the table minimum was much higher.
  - Now: big tables get 1K, 2K, 5K and more, up to 1M, each in its own colour. Chips the table doesn't allow are
    not shown at all — on phones, the laptop and the TV alike.
- **More roulette bets with a mouse or finger**
  - Before: you could only drop a chip on a single number or an outside bet.
  - Now: drop or click a chip on the line between two numbers, the corner where four meet, the edge of a row or
    between two rows. The numbers your bet covers light up while you aim.
- **21 casino table themes**
  - Before: seven plain felt colours.
  - Now: 21 themes, each with its own felt pattern — from Royal and Neon strip to Sakura night, Galaxy and Pixel
    arcade. The host's theme colours every phone, the laptop and the TV at once.
- **Andar Bahar: exact card option**
  - Before: a card won when its value matched (any suit).
  - Now: the host can also pick "exact card" — same value and same suit.
- **Coin Gate intro**
  - Before: the studio opened with a sunset or circuit scene.
  - Now: you can also pick an arcade cabinet — a silver coin drops in and a heavy gate grinds open.
- **Sounds in the studio**
  - Before: the studio was silent.
  - Now: soft clicks, chip sounds, the roulette ball, card deals and more, with an on/off switch and volume for each
    kind of sound.
- **Casino button everywhere**
  - Before: you had to find a casino table in the app list.
  - Now: a gold Casino button sits in the top bar on every screen (with a little coin drop), and the Casino group
    in the app list takes you straight to the tables.

### Better

- **Messages you can't miss**
  - Before: "Table min is …" or "Not enough credits" showed small at the top of the phone, and the host on the
    laptop saw nothing at all.
  - Now: the message pops up big in the middle of the screen on every device.
- **Phone top bar**
  - Before: your credits could run into your picture and the buttons.
  - Now: a cleaner bar with your name and credits on their own plaque; big balances shorten (1,250,000 → 1.25M).
- **Everyone in sync**
  - Before: phones, the laptop and the TV could count down and show results a moment apart.
  - Now: every device follows one shared clock, so countdowns end and results appear at the same moment everywhere.
- **The panel on every phone**
  - Before: phones only saw the betting table.
  - Now: during the spin or the deal, every phone shows the live panel too.
- **Smoother on a Fire TV**
  - Before: animations on slow TV browsers stuttered.
  - Now: heavy effects are gone, and a lighter mode switches on by itself on slow TVs.
- **The winning number on the TV**
  - Before: a white marker, then a rubber stamp, showed where the ball landed.
  - Now: like a real table, the dealer sets a crystal dolly with a gold base on the winning number.
- **The DeskDot logo**
  - Before: the old logo in three colours.
  - Now: an animated LED logo in two colours — pink "Desk", gold "Dot" — on every screen.
- **Intro previews**
  - Before: you had to pick an intro to find out what it looked like.
  - Now: each intro shows a small moving preview under its name in Settings. The OG intro was redrawn: clean,
    smooth and without glare.
- **Theme picker always available**
  - Before: table themes only appeared once a table was running.
  - Now: you can pick a theme any time.

### Fixed

- **Betting from a laptop as a guest**
  - Before: clicking chips with a mouse was laggy or did nothing, and dragging was jumpy.
  - Now: one click places one chip, and dragging follows the mouse smoothly.
- **Leaf Leap and Dig World with phones**
  - Before: a phone joining these games crashed them.
  - Now: friends can join normally.

## 3.4.0 — 4 Oct 2026 · The casino, and DeskDot in your browser

### New

- **Casino mode**
  - Before: DeskDot only had arcade games and apps.
  - Now: nine casino tables — Roulette, 7 Up 7 Down, Blackjack, Baccarat, Slots, Texas Hold'em, Teen Patti, Andar
    Bahar and the Big Six wheel. Friends join with their phones and bet with free play credits (they have no money
    value). Every result can be checked as fair from a phone.
- **Rock Paper Scissors**
  - Before: not available.
  - Now: play the computer, a friend, or a tournament of up to 8 players.
- **DeskDot in the browser**
  - Before: you had to install DeskDot on a computer to use it.
  - Now: open the web app and connect to your panel straight from the browser — nothing to install.
- **Play with friends over the internet**
  - Before: friends had to be on the same Wi-Fi.
  - Now: in the web app, friends can join from anywhere by scanning the code.
- **Camera, screen and music in the browser**
  - Before: Camera Mirror, Screen Mirror and the music visualizer only worked in the installed app.
  - Now: they work in the web app too, after the browser asks your permission.
- **How to play and rulebook**
  - Before: you had to know the casino rules already.
  - Now: every table has a "?" with how to play, the full rules and the payouts, plus a short tour the first time.

### Better

- **Phone version of the studio**
  - Before: the studio was a squeezed-down desktop page on phones.
  - Now: it works like a phone app — a tab bar at the bottom, one screen per tab and sheets that slide up.
- **Casino previews**
  - Before: the casino previews were still pictures.
  - Now: they play a whole demo round.
- **Panel while waiting for bets**
  - Before: the panel kept showing the join code during a game.
  - Now: once someone sits down, it shows the table and who has placed their chips.

### Fixed

- **Apps in the browser**
  - Before: some apps failed quietly in the web app.
  - Now: each one was checked; the ones that can't work in a browser say so and explain why.

## 3.3.0 — 2 Oct 2026 · The fruit fly, and a new name

### New

- **A fruit fly that plays your games**
  - Before: games played themselves with a simple computer player.
  - Now: a model of a real fruit fly's brain watches the panel and plays — and you can watch its brain light up in
    3D next to the game.
- **Colour calibration**
  - Before: colours on the panel could look different from the screen.
  - Now: a guided test matches the panel's colours to your screen.
- **Intro and outro scenes**
  - Before: the studio just appeared.
  - Now: a short animated intro plays while it connects — Sunset, Circuit or the original LED fly-in.
- **Search bar for your computer**
  - Before: you had to open the studio to change what the panel shows.
  - Now: press Ctrl+Alt+Space anywhere and type.
- **Join with your phone**
  - Before: phones were plain controllers.
  - Now: pick your name, colour and character, see who else is in, and get your seat back if you drop out.

### Better

- **New name: DeskDot**
  - Before: the project was called DotDeck.
  - Now: it's DeskDot everywhere. Your old settings still work.
- **Now playing**
  - Before: music info was a small card.
  - Now: a full-screen now-playing view, like a music player.
- **New website**
  - Before: one long page.
  - Now: separate pages with a live preview of every app.

### Fixed

- **Panel reconnects after sleep**
  - Before: after the computer slept, the panel could stay disconnected.
  - Now: DeskDot notices and reconnects by itself.
- **Calendar after midnight**
  - Before: a meeting in progress just after midnight disappeared from the timeline.
  - Now: it shows.

## 3.2.0 — 1 Oct 2026 · First public release

### New

- **22 games with friends**
  - Before: a handful of single-player games.
  - Now: 22 games for 1 to 4 players — versus, co-op, free-for-all and teams — with maps and themes to pick from.
- **Phones as controllers**
  - Before: you played with the keyboard only.
  - Now: the panel shows a code, friends scan it and their phones become controllers, with seven layouts to choose
    from.
- **Android app (beta)**
  - Before: DeskDot needed a computer running.
  - Now: a spare Android phone can run it all day instead.

### Better

- **Smoother, clearer panel**
  - Before: some animations stepped or jumped, and small details were hard to see.
  - Now: every app was reworked to move smoothly and read clearly on the real panel.
- **Game settings in the studio**
  - Before: settings were one long list.
  - Now: they're grouped into Game, Graphics and Game flow, and you set up a match before you play.

### Fixed

- **Privacy**
  - Before: your panel's address was stored in the code.
  - Now: it's kept only in your own settings file, and secrets are hidden everywhere.

## 3.1.0 — 27 Sep 2026 · Presets and 25 new apps

### New

- **Presets**
  - Before: you picked apps one by one.
  - Now: one tap plays a ready-made list — all games, all pets, a desk dashboard and more.
- **25 new apps**
  - Before: a smaller app library.
  - Now: earthquakes, rain radar, air quality, space, trivia, currency and more.

### Fixed

- **Panel freezing**
  - Before: the panel could freeze when pictures were sent too often.
  - Now: DeskDot paces them so it doesn't.

## 3.0.0 — 24 Sep 2026 · The rebuild

### New

- **A brand-new DeskDot**
  - Before: a collection of scripts.
  - Now: rebuilt from scratch as one app with a studio to control the panel, faster and more reliable Bluetooth, and
    support for AI assistants.
