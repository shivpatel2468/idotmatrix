import AppKit
import SwiftUI

/// State of the command bar: query, selection, list vs. display-menu grid.
@MainActor
final class CommandModel: ObservableObject {
    @Published var query = "" { didSet { selection = 0 } }
    @Published var selection = 0
    @Published var grid = false { didSet { selection = 0 } }
    @Published var focusToken = 0 // bumped on every show: refocus + select the field
    @Published var busy: String?
    let store: DeskDotStore
    var close: () -> Void = {}

    static let gridColumns = 5

    init(store: DeskDotStore) { self.store = store }

    var results: [CommandItem] {
        let all = Catalog.build(store)
        let ranked = Catalog.rank(all, extra: Catalog.queryItems(query), query: query, recent: Prefs.recent)
        guard grid else { return ranked }
        let apps = ranked.filter { $0.kind == .app || $0.kind == .game }
        if !query.trimmingCharacters(in: .whitespaces).isEmpty { return apps }
        func order(_ c: String?) -> Int { Category.order.firstIndex(of: c ?? "") ?? 99 }
        return apps.enumerated().sorted { (order($0.element.category), $0.offset) < (order($1.element.category), $1.offset) }
            .map(\.element)
    }

    var current: CommandItem? {
        let r = results
        return r.isEmpty ? nil : r[min(selection, r.count - 1)]
    }

    func move(_ delta: Int) {
        let n = results.count
        guard n > 0 else { return }
        if grid {
            selection = max(0, min(n - 1, selection + delta))
        } else {
            selection = ((selection + delta) % n + n) % n
        }
    }

    private func remember(_ id: String) {
        Prefs.recent = [id] + Prefs.recent.filter { $0 != id }
    }

    func openStudio(_ item: CommandItem?) {
        guard let item else { return }
        remember(item.id)
        store.client.openStudio(item.studio ?? "")
        close()
    }

    func run(_ item: CommandItem?) {
        guard let item, busy == nil else { return }
        if item.kind == .setting || item.id == "now" || item.id == "studio" { return openStudio(item) }
        if item.id == "brightness" { return }
        busy = item.id
        let client = store.client
        Task {
            do {
                if let msg = try await item.run(client) { store.flash(msg) }
                remember(item.id)
                if !item.staysOpen { close() }
            } catch {
                store.flash(error.localizedDescription)
            }
            busy = nil
            await store.refresh(full: false)
        }
    }

    func nudgeBrightness(_ delta: Int) {
        let b = max(5, min(100, Int(store.state?.settings.brightness ?? 60) + delta))
        store.perform("Brightness \(b)%") { c in
            try await c.settings(["brightness": b])
            return "Brightness \(b)%"
        }
    }

    /// Arrow keys, ↵, ⌘↵, Tab and Esc arrive here from the panel's key monitor. Returns true when handled.
    func handleKey(_ event: NSEvent) -> Bool {
        let cmd = event.modifierFlags.contains(.command)
        switch event.keyCode {
        case 125: move(grid ? Self.gridColumns : 1) // ↓
        case 126: move(grid ? -Self.gridColumns : -1) // ↑
        case 123, 124: // ← →
            let d = event.keyCode == 124 ? 1 : -1
            if grid { move(d) } else if current?.id == "brightness" { nudgeBrightness(d * 5) } else { return false }
        case 36, 76: cmd ? openStudio(current) : run(current) // ↵
        case 48: grid.toggle() // Tab
        case 53: // Esc: clear, then hide
            if query.isEmpty { close() } else { query = "" }
        case 121: move(8) // page down
        case 116: move(-8) // page up
        default: return false
        }
        return true
    }
}

struct CommandBarView: View {
    @ObservedObject var model: CommandModel
    @ObservedObject var store: DeskDotStore
    @ObservedObject private var previews = PreviewCache.shared
    @FocusState private var focused: Bool

    var body: some View {
        let results = model.results
        let cur = model.current
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                DotMark(dot: 5)
                Image(systemName: "magnifyingglass").foregroundStyle(Brand.ink3)
                TextField(model.grid ? "Filter the display menu…" : "Search apps, games, presets, controls…  (> to send text)",
                          text: $model.query)
                    .textFieldStyle(.plain)
                    .font(.system(size: 19, weight: .medium))
                    .focused($focused)
                Picker("", selection: $model.grid) {
                    Image(systemName: "list.bullet").tag(false)
                    Image(systemName: "square.grid.2x2").tag(true)
                }
                .pickerStyle(.segmented)
                .frame(width: 84)
                .labelsHidden()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 13)
            Divider().overlay(Brand.line)
            HStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        if !store.online {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Can't reach the DeskDot engine").font(.headline)
                                Text("Start it with `uv run deskdot serve`, or check the engine URL in the menu-bar item.")
                                    .foregroundStyle(Brand.ink3)
                            }
                            .padding(20)
                        } else if model.grid {
                            gridView(results)
                        } else {
                            listView(results)
                        }
                    }
                    .onChange(of: model.selection) { sel in
                        withAnimation(.easeOut(duration: 0.12)) { proxy.scrollTo(sel) }
                    }
                }
                .frame(maxWidth: .infinity)
                Divider().overlay(Brand.line)
                PreviewPane(item: cur, store: store).frame(width: 280)
            }
            Divider().overlay(Brand.line)
            footer(cur)
        }
        .background(Brand.chassis)
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.white.opacity(0.08)))
        .preferredColorScheme(.dark)
        .onAppear { focused = true }
        .onChange(of: model.focusToken) { _ in
            focused = true
            DispatchQueue.main.async { NSApp.keyWindow?.firstResponder.flatMap { $0 as? NSTextView }?.selectAll(nil) }
        }
    }

    private func listView(_ results: [CommandItem]) -> some View {
        LazyVStack(alignment: .leading, spacing: 2) {
            ForEach(Array(results.enumerated()), id: \.element.id) { i, item in
                Row(item: item, selected: i == model.selection, busy: model.busy == item.id, query: model.query)
                    .id(i)
                    .contentShape(Rectangle())
                    .onTapGesture { model.selection = i; model.run(item) }
                    .onHover { if $0 { model.selection = i } }
            }
        }
        .padding(6)
    }

    private func gridView(_ results: [CommandItem]) -> some View {
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: CommandModel.gridColumns), spacing: 6) {
            ForEach(Array(results.enumerated()), id: \.element.id) { i, item in
                VStack(spacing: 5) {
                    LEDView(image: item.app.flatMap { previews.image(for: $0) }, size: 58)
                    Text(item.title).font(.system(size: 11)).lineLimit(1)
                        .foregroundStyle(i == model.selection ? Color.white : Brand.ink2)
                }
                .padding(6)
                .background(RoundedRectangle(cornerRadius: 10).fill(i == model.selection ? Brand.chassis2 : .clear))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(i == model.selection ? Brand.tangerine.opacity(0.4) : .clear))
                .id(i)
                .contentShape(Rectangle())
                .onTapGesture { model.selection = i; model.run(item) }
                .onHover { if $0 { model.selection = i } }
            }
        }
        .padding(8)
    }

    private func footer(_ cur: CommandItem?) -> some View {
        HStack(spacing: 8) {
            Circle().fill(store.online ? (store.state?.device.status == "connected" ? Color.green : Color.orange) : Color.red)
                .frame(width: 7, height: 7)
            Text(store.online ? "\(store.state?.device.name ?? "Panel") · \(store.state?.device.status ?? "…")" : "Engine offline")
                .foregroundStyle(Brand.ink3)
            if let t = store.toast { Text(t).foregroundStyle(Brand.gold).lineLimit(1) }
            Spacer()
            if let cur {
                Hint(key: "↵", text: cur.id == "brightness" ? "← → adjust" : cur.verb)
                if cur.studio != nil { Hint(key: "⌘↵", text: "Studio") }
            }
            Hint(key: "Tab", text: model.grid ? "List" : "Display menu")
            Hint(key: "Esc", text: "Hide")
        }
        .font(.system(size: 11))
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
    }
}

private struct Hint: View {
    let key: String
    let text: String
    var body: some View {
        HStack(spacing: 4) {
            Text(key).font(.system(size: 10, design: .monospaced))
                .padding(.horizontal, 5).padding(.vertical, 1)
                .background(RoundedRectangle(cornerRadius: 4).fill(Brand.chassis2))
                .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Brand.line))
            Text(text).foregroundStyle(Brand.ink3)
        }
    }
}

private struct Row: View {
    let item: CommandItem
    let selected: Bool
    let busy: Bool
    let query: String

    var body: some View {
        HStack(spacing: 11) {
            Image(systemName: item.symbol)
                .frame(width: 30, height: 30)
                .foregroundStyle(selected ? Brand.tangerine : (item.kind == .fly ? Brand.gold : Brand.ink2))
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.white.opacity(0.04)))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Brand.line))
            VStack(alignment: .leading, spacing: 1) {
                Text(item.title).font(.system(size: 13.5, weight: .semibold)).lineLimit(1)
                Text(item.subtitle).font(.system(size: 11.5)).foregroundStyle(Brand.ink3).lineLimit(1)
            }
            Spacer(minLength: 4)
            if busy { ProgressView().controlSize(.small) } else {
                Text(kindLabel).font(.system(size: 9.5, design: .monospaced)).foregroundStyle(Brand.ink3.opacity(0.7))
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 10).fill(selected ? Brand.chassis2 : .clear)
        )
        .overlay(alignment: .leading) {
            if selected { Capsule().fill(Brand.gradient).frame(width: 3).padding(.vertical, 9) }
        }
    }

    private var kindLabel: String {
        switch item.kind {
        case .game: return "GAME"
        case .app: return (Category.label[item.category ?? ""] ?? "App").uppercased()
        case .preset: return "PRESET"
        case .setting: return "SETTINGS"
        case .fly: return "FLY"
        case .say: return "SEND"
        case .now: return "LIVE"
        case .action: return "CONTROL"
        }
    }
}

private struct PreviewPane: View {
    let item: CommandItem?
    @ObservedObject var store: DeskDotStore
    @ObservedObject private var previews = PreviewCache.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let item {
                HStack { Spacer(); hero(item); Spacer() }.frame(minHeight: 186)
                Text(item.title).font(.system(size: 16, weight: .bold)).lineLimit(2)
                Text(description(item)).font(.system(size: 12)).foregroundStyle(Brand.ink2)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
                facts(item)
            }
        }
        .padding(18)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(Color.black.opacity(0.15))
    }

    @ViewBuilder private func hero(_ item: CommandItem) -> some View {
        if item.id == "now" {
            LEDView(image: store.frame, size: 176)
        } else if item.id == "brightness" || item.id == "brightness-set" {
            let b = item.id == "brightness" ? Int(store.state?.settings.brightness ?? 60)
                : Int(item.title.filter(\.isNumber)) ?? 60
            VStack(spacing: 10) {
                Image(systemName: "sun.max.fill").font(.system(size: 30)).foregroundStyle(Brand.gold)
                Text("\(b)%").font(.system(size: 34, weight: .semibold))
                if item.id == "brightness" {
                    Slider(value: Binding(
                        get: { store.state?.settings.brightness ?? 60 },
                        set: { v in
                            let b = Int(v)
                            store.perform("Brightness \(b)%") { c in try await c.settings(["brightness": b]); return nil }
                        }
                    ), in: 5 ... 100, step: 5)
                        .tint(Brand.tangerine)
                }
            }
        } else if let app = item.app, [.app, .game, .fly].contains(item.kind) {
            LEDView(image: previews.image(for: app), size: 176)
        } else {
            Image(systemName: item.symbol).font(.system(size: 40, weight: .light)).foregroundStyle(Brand.tangerine)
                .frame(width: 96, height: 96)
                .background(RoundedRectangle(cornerRadius: 24).fill(Brand.chassis2))
        }
    }

    private func description(_ item: CommandItem) -> String {
        if item.kind == .preset, let p = store.presets.first(where: { "preset:\($0.id)" == item.id }) {
            let names = p.items.prefix(12).map { i in store.meta?.apps.first { $0.id == i.app }?.name ?? i.app }
            return names.joined(separator: " · ") + (p.items.count > 12 ? " …" : "")
        }
        return item.subtitle
    }

    @ViewBuilder private func facts(_ item: CommandItem) -> some View {
        let app = store.meta?.apps.first { $0.id == item.app }
        VStack(alignment: .leading, spacing: 4) {
            if let app, item.kind != .fly {
                Fact(k: "CATEGORY", v: Category.label[app.category] ?? app.category)
                Fact(k: "SETTINGS", v: "\(app.settingTitles.count)")
                if (app.maxPlayers ?? 1) > 1 { Fact(k: "PLAYERS", v: "up to \(app.maxPlayers ?? 1)") }
            }
            if item.id == "now", let s = store.state {
                Fact(k: "MODE", v: s.playlistPlaying ? "Playlist" : "Manual")
                Fact(k: "BRIGHTNESS", v: "\(Int(s.settings.brightness))%")
            }
        }
    }
}

private struct Fact: View {
    let k: String
    let v: String
    var body: some View {
        HStack {
            Text(k).font(.system(size: 9.5, design: .monospaced)).foregroundStyle(Brand.ink3)
            Spacer()
            Text(v).font(.system(size: 11.5)).foregroundStyle(Brand.ink2)
        }
    }
}
