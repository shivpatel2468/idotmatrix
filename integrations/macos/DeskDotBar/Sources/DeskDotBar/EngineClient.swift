import AppKit
import Foundation

/// The DeskDot engine's HTTP API. DeskDot Bar never touches Bluetooth: the engine owns the panel link.
struct EngineClient {
    var base: String

    struct Failure: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }

    private func url(_ path: String) throws -> URL {
        guard let u = URL(string: base.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + path) else {
            throw Failure(message: "Bad engine URL: \(base)")
        }
        return u
    }

    private func send(_ method: String, _ path: String, body: [String: Any]? = nil) async throws -> Data {
        var req = URLRequest(url: try url(path), timeoutInterval: 4)
        req.httpMethod = method
        if let body {
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
            req.setValue("application/json", forHTTPHeaderField: "content-type")
        }
        let data: Data
        let resp: URLResponse
        do {
            (data, resp) = try await URLSession.shared.data(for: req)
        } catch {
            throw Failure(message: "DeskDot isn't running at \(base)")
        }
        if let http = resp as? HTTPURLResponse, !(200 ..< 300).contains(http.statusCode) {
            if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let d = obj["detail"] as? String {
                throw Failure(message: d)
            }
            throw Failure(message: "HTTP \(http.statusCode)")
        }
        return data
    }

    private func get<T: Decodable>(_ path: String, as _: T.Type) async throws -> T {
        try JSONDecoder().decode(T.self, from: try await send("GET", path))
    }

    private func esc(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? s
    }

    // ------------------------------------------------------------------ read
    func meta() async throws -> Meta { try await get("/api/meta", as: Meta.self) }
    func state() async throws -> EngineState { try await get("/api/state", as: EngineState.self) }
    func presets() async throws -> [Preset] { try await get("/api/presets", as: [Preset].self) }

    func frame(scale: Int = 1) async throws -> NSImage? {
        NSImage(data: try await send("GET", "/api/frame.png?scale=\(scale)"))
    }

    func preview(_ app: String) async throws -> NSImage? {
        NSImage(data: try await send("GET", "/api/apps/\(esc(app))/preview.gif"))
    }

    // ------------------------------------------------------------------ write
    func activate(_ app: String) async throws { _ = try await send("POST", "/api/apps/\(esc(app))/activate", body: [:]) }
    func patchSettings(_ app: String, _ patch: [String: Any]) async throws {
        _ = try await send("PATCH", "/api/apps/\(esc(app))/settings", body: patch)
    }
    func action(_ app: String, _ action: String) async throws {
        _ = try await send("POST", "/api/apps/\(esc(app))/actions/\(esc(action))", body: [:])
    }
    func playPreset(_ id: String, shuffle: Bool = false) async throws {
        _ = try await send("POST", "/api/presets/\(esc(id))/play", body: ["shuffle": shuffle])
    }
    func playlist(_ op: String) async throws { _ = try await send("POST", "/api/playlist/\(op)") }
    func settings(_ patch: [String: Any]) async throws { _ = try await send("PATCH", "/api/settings", body: patch) }
    func notify(_ message: String) async throws {
        _ = try await send("POST", "/api/notify", body: [
            "title": "", "message": message, "color": "#ff7419", "icon": "bell", "duration": 8, "style": "banner",
        ])
    }
    func text(_ text: String) async throws {
        _ = try await send("POST", "/api/text", body: ["text": text, "color": "#ffcc33", "revert_after": 30])
    }

    /// The fruit-fly brain plays `app` (a game), or the game on the panel, or its own Fly Brain app.
    func flyPlay(meta: Meta?, current: String?, app: String? = nil) async throws -> String {
        let target = app ?? current
        if let target, let m = meta?.apps.first(where: { $0.id == target }), m.flyCanPilot {
            try await patchSettings(target, ["pilot": "fly"])
            if app != nil { try await activate(target) }
            try? await action(target, "fly")
            return "The fly is playing \(m.name)"
        }
        try await activate("flybrain")
        return "The fly is on the panel"
    }

    /// Studio deep links: `#app/<id>` selects an app, `#settings/<section>` opens settings.
    func openStudio(_ hash: String = "") {
        if let u = URL(string: base.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/" + hash) {
            NSWorkspace.shared.open(u)
        }
    }
}
