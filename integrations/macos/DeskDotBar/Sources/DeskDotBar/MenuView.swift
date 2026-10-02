import AppKit
import SwiftUI

/// The popover under the menu-bar item: what's on the panel + quick controls.
struct MenuView: View {
    @ObservedObject var store: DeskDotStore
    var openCommandBar: () -> Void
    var hotkeyChanged: () -> Void
    @State private var engineURL = Prefs.engineURL
    @State private var hotkey = Prefs.hotkey
    @State private var showSettings = false
    @State private var brightness: Double = 60

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                LEDView(image: store.frame, size: 96)
                VStack(alignment: .leading, spacing: 4) {
                    Text("NOW SHOWING").font(.system(size: 9.5, design: .monospaced)).foregroundStyle(Brand.ink3)
                    Text(store.currentApp?.name ?? (store.online ? "—" : "Engine offline"))
                        .font(.system(size: 15, weight: .bold)).lineLimit(2)
                    HStack(spacing: 5) {
                        Circle().fill(statusColor).frame(width: 6, height: 6)
                        Text(statusText).font(.system(size: 11)).foregroundStyle(Brand.ink2)
                    }
                    if let t = store.toast { Text(t).font(.system(size: 11)).foregroundStyle(Brand.gold) }
                }
                Spacer()
            }

            HStack(spacing: 8) {
                Image(systemName: "sun.min").foregroundStyle(Brand.ink3)
                Slider(value: $brightness, in: 5 ... 100, step: 5, onEditingChanged: { editing in
                    if !editing { setBrightness() }
                })
                .tint(Brand.tangerine)
                Text("\(Int(brightness))%").font(.system(size: 11, design: .monospaced)).frame(width: 36)
            }
            .disabled(!store.online)

            HStack(spacing: 8) {
                ControlButton(symbol: "backward.end.fill", help: "Previous") {
                    store.perform("Previous") { c in try await c.playlist("prev"); return nil }
                }
                ControlButton(symbol: store.state?.playlistPlaying == true ? "stop.fill" : "play.fill",
                              help: "Play / stop the playlist") {
                    let playing = store.state?.playlistPlaying == true
                    store.perform(playing ? "Playlist stopped" : "Playlist playing") { c in
                        try await c.playlist(playing ? "stop" : "play"); return nil
                    }
                }
                ControlButton(symbol: "forward.end.fill", help: "Next") {
                    store.perform("Next") { c in try await c.playlist("next"); return nil }
                }
                ControlButton(symbol: "power", help: "Panel power", tint: store.state?.settings.power == false ? .red : nil) {
                    let on = store.state?.settings.power ?? true
                    store.perform(on ? "Panel off" : "Panel on") { c in try await c.settings(["power": !on]); return nil }
                }
                ControlButton(symbol: "ladybug.fill", help: "Let the fly play", tint: Brand.gold) {
                    let meta = store.meta
                    let cur = store.state?.engine.current?.app
                    store.perform("The fly") { c in try await c.flyPlay(meta: meta, current: cur) }
                }
            }
            .disabled(!store.online)

            if !store.presets.isEmpty {
                Menu {
                    ForEach(store.presets) { p in
                        Button(p.name + (store.state?.engine.activePreset == p.id ? "  ✓" : "")) {
                            store.perform("Playing “\(p.name)”") { c in try await c.playPreset(p.id); return nil }
                        }
                    }
                } label: {
                    Label("Presets", systemImage: "list.bullet")
                }
                .menuStyle(.borderlessButton)
            }

            Divider()
            MenuRow(title: "Search DeskDot…", shortcut: HotKeyChoice.current.label, action: openCommandBar)
            MenuRow(title: "Open Studio", shortcut: nil) { store.client.openStudio() }
            MenuRow(title: "Settings…", shortcut: nil) { showSettings.toggle() }
            if showSettings {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Engine URL").font(.system(size: 11)).foregroundStyle(Brand.ink3)
                    TextField(Prefs.defaultURL, text: $engineURL, onCommit: applyURL)
                        .textFieldStyle(.roundedBorder)
                    Picker("Command bar", selection: $hotkey) {
                        ForEach(HotKeyChoice.all) { Text($0.label).tag($0.id) }
                    }
                    .onChange(of: hotkey) { v in
                        Prefs.hotkey = v
                        hotkeyChanged()
                    }
                    Button("Save URL", action: applyURL)
                }
                .padding(.leading, 6)
            }
            Divider()
            MenuRow(title: "Quit DeskDot Bar", shortcut: "⌘Q") { NSApp.terminate(nil) }
        }
        .padding(14)
        .frame(width: 320)
        .onAppear { brightness = store.state?.settings.brightness ?? brightness }
        .onReceive(store.$state) { s in if let b = s?.settings.brightness { brightness = b } }
    }

    private var statusColor: Color {
        guard store.online else { return .red }
        return store.state?.device.status == "connected" ? .green : .orange
    }

    private var statusText: String {
        guard store.online, let d = store.state?.device else { return "Start it: uv run deskdot serve" }
        return "\(d.name ?? (d.kind == "sim" ? "Simulator" : "Panel")) · \(d.status)"
    }

    private func setBrightness() {
        let b = Int(brightness)
        store.perform("Brightness \(b)%") { c in try await c.settings(["brightness": b]); return nil }
    }

    private func applyURL() {
        let u = engineURL.trimmingCharacters(in: .whitespacesAndNewlines)
        Prefs.engineURL = u.isEmpty ? Prefs.defaultURL : u
        PreviewCache.shared.clear()
        Task { await store.refresh(full: true) }
    }
}

private struct ControlButton: View {
    let symbol: String
    let help: String
    var tint: Color?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .frame(maxWidth: .infinity, minHeight: 28)
                .foregroundStyle(tint ?? Color.primary)
        }
        .buttonStyle(.bordered)
        .help(help)
    }
}

private struct MenuRow: View {
    let title: String
    let shortcut: String?
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack {
                Text(title)
                Spacer()
                if let shortcut { Text(shortcut).foregroundStyle(Brand.ink3) }
            }
            .padding(.vertical, 4)
            .padding(.horizontal, 6)
            .background(RoundedRectangle(cornerRadius: 6).fill(hover ? Color.white.opacity(0.08) : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}
