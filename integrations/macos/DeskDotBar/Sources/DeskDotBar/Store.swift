import AppKit
import Combine
import Foundation

/// User preferences (UserDefaults): engine URL and the command-bar hotkey.
enum Prefs {
    static let defaultURL = "http://127.0.0.1:8765"
    static var engineURL: String {
        get { UserDefaults.standard.string(forKey: "engineURL") ?? defaultURL }
        set { UserDefaults.standard.set(newValue, forKey: "engineURL") }
    }
    static var hotkey: String {
        get { UserDefaults.standard.string(forKey: "hotkey") ?? HotKeyChoice.all[0].id }
        set { UserDefaults.standard.set(newValue, forKey: "hotkey") }
    }
    static var recent: [String] {
        get { UserDefaults.standard.stringArray(forKey: "recent") ?? [] }
        set { UserDefaults.standard.set(Array(newValue.prefix(12)), forKey: "recent") }
    }
}

/// Live engine state shared by the menu-bar item, its popover and the command bar.
@MainActor
final class DeskDotStore: ObservableObject {
    @Published var meta: Meta?
    @Published var state: EngineState?
    @Published var presets: [Preset] = []
    @Published var frame: NSImage?
    @Published var online = false
    @Published var toast: String?

    /// true while the popover or the command bar is open: poll faster
    var interactive = false {
        didSet { if interactive { Task { await refresh(full: true) } } }
    }

    var client: EngineClient { EngineClient(base: Prefs.engineURL) }
    private var timer: Timer?
    private var tick = 0
    private var metaAge = Date.distantPast

    func start() {
        Task { await refresh(full: true) }
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.poll() }
        }
    }

    private func poll() async {
        tick += 1
        // interactive: frame 2 Hz, state 0.5 Hz · idle: frame and state every 4 s (the menu-bar mini preview)
        let every = interactive ? 1 : 8
        guard tick % every == 0 else { return }
        if let img = try? await client.frame(scale: 1) {
            frame = img
        }
        if !interactive || tick % 4 == 0 { await refresh(full: false) }
    }

    func refresh(full: Bool) async {
        let c = client
        do {
            state = try await c.state()
            if full || meta == nil || Date().timeIntervalSince(metaAge) > 60 {
                meta = try await c.meta()
                presets = (try? await c.presets()) ?? presets
                metaAge = Date()
            }
            online = true
        } catch {
            online = false
        }
    }

    var currentApp: AppMeta? {
        guard let id = state?.engine.current?.app else { return nil }
        return meta?.apps.first { $0.id == id }
    }

    /// Run an engine call, show its result briefly, refresh.
    func perform(_ label: String, _ work: @escaping (EngineClient) async throws -> String?) {
        let c = client
        Task {
            do {
                let msg = try await work(c)
                self.flash(msg ?? label)
            } catch {
                self.flash(error.localizedDescription)
            }
            await self.refresh(full: false)
        }
    }

    func flash(_ text: String) {
        toast = text
        let shown = text
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.4) { [weak self] in
            if self?.toast == shown { self?.toast = nil }
        }
    }
}

/// GIF/PNG previews by app id, cached (the engine renders them in a sandbox and caches for 20 s).
@MainActor
final class PreviewCache: ObservableObject {
    static let shared = PreviewCache()
    private var images: [String: NSImage] = [:]
    private var loading: Set<String> = []
    @Published private(set) var version = 0

    func image(for app: String) -> NSImage? {
        if let img = images[app] { return img }
        guard !loading.contains(app) else { return nil }
        loading.insert(app)
        let c = EngineClient(base: Prefs.engineURL)
        Task {
            if let img = try? await c.preview(app) {
                self.images[app] = img
                self.version += 1
            }
            self.loading.remove(app)
        }
        return nil
    }

    func clear() {
        images.removeAll()
        version += 1
    }
}
