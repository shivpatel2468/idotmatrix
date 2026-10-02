import Foundation

/// One row in the command bar. The same catalogue as the web launcher (web/src/launcher/search.ts).
struct CommandItem: Identifiable {
    enum Kind { case now, action, app, game, fly, preset, setting, say }

    let id: String
    let kind: Kind
    let title: String
    let subtitle: String
    var keywords = ""
    var app: String?
    var category: String?
    /// studio deep link for ⌘↵
    var studio: String?
    var verb = "Open"
    /// listed only once something is typed (settings, per-game fly items…)
    var searchOnly = false
    /// typed-text fallbacks go after the real matches
    var fallback = false
    var symbol = "sparkles"
    /// leave the bar open after ↵ (things you press repeatedly)
    var staysOpen = false
    let run: (EngineClient) async throws -> String?
}

enum Catalog {
    static let settings: [(tab: String, title: String, words: String)] = [
        ("display", "Display", "brightness transition flip night mode hz fps"),
        ("panel", "Panel", "power flip orientation"),
        ("calibrate", "Colour calibration", "color gamma white balance wizard"),
        ("transfer", "Transfer speed", "bluetooth packet gap fps hz smooth"),
        ("alerts", "Alerts", "notifications on air eye break indicators"),
        ("notifications", "OS notifications", "toast mac alerts banner"),
        ("integrations", "Integrations", "on air ntfy home assistant eye break webcam microphone"),
        ("playlist", "Playlist", "rotation queue presets durations"),
        ("autopilot", "Autopilot", "foreground app rules automatic"),
        ("device", "Device & Bluetooth", "connect reconnect scan address ble link"),
        ("handoff", "Hand-off", "sleep shutdown clock release"),
        ("audio", "Audio source", "music visualiser microphone system sound"),
        ("weather", "Weather & location", "city units metric imperial"),
    ]

    @MainActor
    static func build(_ store: DeskDotStore) -> [CommandItem] {
        let meta = store.meta
        let state = store.state
        let apps = (meta?.apps ?? []).filter { $0.supported != false }
        func name(_ id: String?) -> String { apps.first { $0.id == id }?.name ?? id ?? "nothing" }
        let cur = state?.engine.current?.app
        let power = state?.settings.power ?? true
        let playing = state?.playlistPlaying ?? false
        let bri = Int(state?.settings.brightness ?? 60)
        var items: [CommandItem] = []

        items.append(CommandItem(id: "now", kind: .now, title: "Now showing: \(name(cur))",
                                 subtitle: playing ? "Playlist is playing" : "Live view of the panel",
                                 keywords: "now playing current panel live", app: cur,
                                 studio: cur.map { "#app/\($0)" } ?? "", verb: "Open studio", symbol: "display",
                                 run: { _ in nil }))
        items.append(CommandItem(id: "brightness", kind: .action, title: "Brightness",
                                 subtitle: "\(bri)%  ·  ← → to adjust, or type “b 40”",
                                 keywords: "brightness dim light level", studio: "#settings/display",
                                 verb: "Adjust", symbol: "sun.max", staysOpen: true, run: { _ in nil }))
        items.append(CommandItem(id: "next", kind: .action, title: "Next", subtitle: "Skip to the next playlist item",
                                 keywords: "next skip forward playlist", verb: "Next", symbol: "forward.end",
                                 staysOpen: true, run: { c in try await c.playlist("next"); return "Next" }))
        items.append(CommandItem(id: "prev", kind: .action, title: "Previous",
                                 subtitle: "Back to the previous playlist item", keywords: "previous back prev playlist",
                                 verb: "Previous", symbol: "backward.end", staysOpen: true,
                                 run: { c in try await c.playlist("prev"); return "Previous" }))
        items.append(CommandItem(id: "power", kind: .action, title: power ? "Turn the panel off" : "Turn the panel on",
                                 subtitle: power ? "Display power off (Bluetooth stays up)" : "Display power on",
                                 keywords: "power on off screen sleep wake display", verb: power ? "Turn off" : "Turn on",
                                 symbol: "power", staysOpen: true,
                                 run: { c in try await c.settings(["power": !power]); return power ? "Panel off" : "Panel on" }))
        items.append(CommandItem(id: "playlist", kind: .action, title: playing ? "Stop the playlist" : "Play the playlist",
                                 subtitle: playing ? "Stay on the current app" : "Rotate through your playlist",
                                 keywords: "playlist play stop pause rotation", studio: "#settings/playlist",
                                 verb: playing ? "Stop" : "Play", symbol: "music.note.list", staysOpen: true,
                                 run: { c in
                                     try await c.playlist(playing ? "stop" : "play")
                                     return playing ? "Playlist stopped" : "Playlist playing"
                                 }))
        let curMeta = apps.first { $0.id == cur }
        items.append(CommandItem(id: "fly", kind: .fly, title: "Let the fly play",
                                 subtitle: curMeta?.flyCanPilot == true ? "A fruit-fly brain takes over \(name(cur))"
                                     : "A fruit-fly brain on the panel (Fly Brain)",
                                 keywords: "fly fruit brain ai play itself drosophila pilot", app: "flybrain",
                                 studio: "", verb: "Let it play", symbol: "ladybug",
                                 run: { c in try await c.flyPlay(meta: meta, current: cur) }))
        items.append(CommandItem(id: "studio", kind: .action, title: "Open DeskDot Studio",
                                 subtitle: "The full editor in your browser", keywords: "studio open browser editor",
                                 studio: "", verb: "Open", symbol: "square.grid.2x2", run: { _ in nil }))

        for p in store.presets {
            items.append(CommandItem(id: "preset:\(p.id)", kind: .preset, title: p.name,
                                     subtitle: "Preset · \(p.items.count) apps\(p.builtin ? "" : " · yours")",
                                     keywords: "preset playlist mix " + p.items.map { name($0.app) }.joined(separator: " "),
                                     studio: "#settings/playlist", verb: "Play preset", symbol: "list.bullet",
                                     run: { c in try await c.playPreset(p.id); return "Playing “\(p.name)”" }))
        }
        for a in apps {
            let game = a.category == "games"
            let kw = [a.id, a.description, Category.label[a.category] ?? a.category, a.category]
                + a.settingTitles
            items.append(CommandItem(id: "app:\(a.id)", kind: game ? .game : .app, title: a.name,
                                     subtitle: a.description, keywords: kw.joined(separator: " "), app: a.id,
                                     category: a.category, studio: "#app/\(a.id)",
                                     verb: game ? "Play on panel" : "Show on panel",
                                     symbol: Category.symbol[a.category] ?? "sparkles",
                                     run: { c in try await c.activate(a.id); return "\(a.name) is on the panel" }))
            if a.flyCanPilot {
                items.append(CommandItem(id: "fly:\(a.id)", kind: .fly, title: "Play \(a.name) with the fly",
                                         subtitle: "The fruit-fly brain plays it, seeing only the pixels",
                                         keywords: "fly brain \(a.name) game pilot", app: a.id, category: a.category,
                                         studio: "#app/\(a.id)", verb: "Let the fly play", searchOnly: true,
                                         symbol: "ladybug",
                                         run: { c in try await c.flyPlay(meta: meta, current: cur, app: a.id) }))
            }
        }
        for s in settings {
            items.append(CommandItem(id: "setting:\(s.tab)", kind: .setting, title: "\(s.title) settings",
                                     subtitle: "Opens in the studio", keywords: "settings preferences \(s.words)",
                                     studio: "#settings/\(s.tab)", verb: "Open settings", searchOnly: true,
                                     symbol: "gearshape", run: { _ in nil }))
        }
        return items
    }

    /// Items made from the query: "b 40" sets brightness, "> hello" (or any text) goes to the panel.
    static func queryItems(_ query: String) -> [CommandItem] {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return [] }
        var out: [CommandItem] = []
        if let m = q.range(of: #"^(b|br|bri|bright|brightness)\s*\d{1,3}\s*%?$"#, options: [.regularExpression, .caseInsensitive]),
           m.lowerBound == q.startIndex {
            let digits = q.filter(\.isNumber)
            let v = max(5, min(100, Int(digits) ?? 60))
            out.append(CommandItem(id: "brightness-set", kind: .action, title: "Set brightness to \(v)%",
                                   subtitle: "Panel brightness", verb: "Set", symbol: "sun.max", staysOpen: true,
                                   run: { c in try await c.settings(["brightness": v]); return "Brightness \(v)%" }))
        }
        var text = q
        var explicit = false
        for prefix in [">", "say ", "notify ", "send "] where q.lowercased().hasPrefix(prefix) {
            text = String(q.dropFirst(prefix.count)).trimmingCharacters(in: .whitespaces)
            explicit = true
            break
        }
        if !text.isEmpty {
            out.append(CommandItem(id: "say-notify", kind: .say, title: "Send “\(text)” to the panel",
                                   subtitle: "Notification banner", verb: "Send", fallback: !explicit,
                                   symbol: "paperplane", run: { c in try await c.notify(text); return "Sent" }))
            out.append(CommandItem(id: "say-text", kind: .say, title: "Show “\(text)” for 30 s",
                                   subtitle: "Scrolling text, then back to what was on", verb: "Show",
                                   fallback: !explicit, symbol: "text.bubble",
                                   run: { c in try await c.text(text); return "On the panel for 30 s" }))
        }
        return out
    }

    // ------------------------------------------------------------------ fuzzy ranking
    private static func norm(_ s: String) -> String {
        s.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: nil)
    }

    private static func titleScore(_ token: String, _ title: String) -> Int {
        if title == token { return 120 }
        if title.hasPrefix(token) { return 90 }
        let words = title.split(whereSeparator: { " -_/·:()“”\"".contains($0) })
        if words.contains(where: { $0.hasPrefix(token) }) { return 70 }
        if title.contains(token) { return 50 }
        // subsequence: "nwp" → "now playing"
        var it = token.makeIterator()
        var want = it.next()
        var matched = 0
        for ch in title where want != nil {
            if ch == want {
                matched += 1
                want = it.next()
            }
        }
        return want == nil && token.count >= 2 && matched == token.count ? 16 : 0
    }

    static func score(_ query: String, _ item: CommandItem) -> Int {
        let q = norm(query.trimmingCharacters(in: .whitespaces))
        if q.isEmpty { return 1 }
        let title = norm(item.title)
        let kw = norm(item.subtitle + " " + item.keywords)
        let whole = titleScore(q, title)
        var total = whole > 0 ? whole + 40 : 0
        if whole == 0 {
            for t in q.split(separator: " ").map(String.init) {
                let s = titleScore(t, title)
                if s > 0 { total += s } else if kw.contains(t) { total += t.count >= 3 ? 18 : 6 } else { return 0 }
            }
        }
        if item.kind == .fly && item.searchOnly && !q.contains("fly") { total -= 25 }
        return max(total, 1)
    }

    static func rank(_ items: [CommandItem], extra: [CommandItem], query: String, recent: [String]) -> [CommandItem] {
        let q = query.trimmingCharacters(in: .whitespaces)
        if q.isEmpty {
            let byID = Dictionary(items.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
            let rec = recent.compactMap { byID[$0] }
            let recIDs = Set(rec.map(\.id))
            return rec + items.filter { !$0.searchOnly && !recIDs.contains($0.id) }
        }
        let scored = items.compactMap { it -> (CommandItem, Int)? in
            var s = score(q, it)
            guard s > 0 else { return nil }
            if let r = recent.firstIndex(of: it.id) { s += 24 - r * 2 }
            return (it, s)
        }
        .sorted { $0.1 > $1.1 }
        .map(\.0)
        return extra.filter { !$0.fallback } + scored + extra.filter(\.fallback)
    }
}
