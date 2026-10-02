import Foundation

// Mirrors of the engine's JSON (docs/API.md). Only the fields DeskDot Bar uses; unknown keys are ignored.

struct SchemaProp: Decodable {
    let title: String?
}

struct AppSchema: Decodable {
    let properties: [String: SchemaProp]?
}

struct AppMeta: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let description: String
    let icon: String
    let category: String
    let schema: AppSchema?
    let maxPlayers: Int?
    let supported: Bool?

    enum CodingKeys: String, CodingKey {
        case id, name, description, icon, category, schema, supported
        case maxPlayers = "max_players"
    }

    static func == (a: AppMeta, b: AppMeta) -> Bool { a.id == b.id }
    func hash(into h: inout Hasher) { h.combine(id) }

    /// Games built on GameApp have a `pilot` setting: the fruit-fly brain can play them.
    var flyCanPilot: Bool { schema?.properties?["pilot"] != nil }
    var settingTitles: [String] { (schema?.properties ?? [:]).values.compactMap(\.title) }
}

struct Meta: Decodable {
    let version: String
    let apps: [AppMeta]
}

struct PresetItem: Decodable {
    let app: String
    let duration: Double
}

struct Preset: Decodable, Identifiable {
    let id: String
    let name: String
    let icon: String
    let builtin: Bool
    let items: [PresetItem]
}

struct DeviceInfo: Decodable {
    let status: String
    let name: String?
    let kind: String
}

struct CurrentApp: Decodable {
    let app: String
}

struct PlaylistInfo: Decodable {
    let enabled: Bool
}

struct EngineInfo: Decodable {
    let mode: String
    let current: CurrentApp?
    let playlist: PlaylistInfo
    let activePreset: String?

    enum CodingKeys: String, CodingKey {
        case mode, current, playlist
        case activePreset = "active_preset"
    }
}

struct GlobalSettings: Decodable {
    let brightness: Double
    let power: Bool
}

struct EngineState: Decodable {
    let device: DeviceInfo
    let engine: EngineInfo
    let settings: GlobalSettings

    var playlistPlaying: Bool { engine.mode == "playlist" && engine.playlist.enabled }
}

enum Category {
    static let order = ["time", "data", "media", "pets", "games", "creative", "productivity", "ambient", "device"]
    static let label: [String: String] = [
        "time": "Time", "data": "Live data", "media": "Media", "creative": "Create", "ambient": "Ambient",
        "productivity": "Focus & agents", "pets": "Pets & characters", "games": "Games", "device": "Panel",
    ]
    static let symbol: [String: String] = [
        "time": "clock", "data": "bolt", "media": "music.note", "creative": "paintpalette", "ambient": "sparkles",
        "productivity": "checklist", "pets": "pawprint", "games": "gamecontroller", "device": "display",
    ]
}
