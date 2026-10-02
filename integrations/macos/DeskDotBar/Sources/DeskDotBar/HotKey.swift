import Carbon
import Foundation

/// Carbon calls this (a plain C function) for every registered hotkey; it hops to the main actor.
private func hotKeyEventHandler(_: EventHandlerCallRef?, _ event: EventRef?, _: UnsafeMutableRawPointer?) -> OSStatus {
    var hk = EventHotKeyID()
    let err = GetEventParameter(
        event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
        nil, MemoryLayout<EventHotKeyID>.size, nil, &hk
    )
    if err == noErr {
        let id = hk.id
        Task { @MainActor in HotKey.fire(id) }
    }
    return noErr
}

/// A system-wide shortcut via Carbon's RegisterEventHotKey: no Accessibility permission needed.
@MainActor
final class HotKey {
    private static var handlers: [UInt32: () -> Void] = [:]
    private static var nextID: UInt32 = 1
    private static var installed = false

    private var ref: EventHotKeyRef?
    private let id: UInt32
    private(set) var registered = false

    init(keyCode: UInt32, modifiers: UInt32, handler: @escaping () -> Void) {
        if !HotKey.installed {
            HotKey.installed = true
            var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
            InstallEventHandler(GetApplicationEventTarget(), hotKeyEventHandler, 1, &spec, nil, nil)
        }
        id = HotKey.nextID
        HotKey.nextID += 1
        HotKey.handlers[id] = handler
        let hkID = EventHotKeyID(signature: OSType(0x4444_4B42), id: id) // 'DDKB'
        registered = RegisterEventHotKey(keyCode, modifiers, hkID, GetApplicationEventTarget(), 0, &ref) == noErr
    }

    /// Unregister (call before dropping the last reference).
    func unregister() {
        if let ref { UnregisterEventHotKey(ref) }
        ref = nil
        HotKey.handlers[id] = nil
    }

    static func fire(_ id: UInt32) {
        handlers[id]?()
    }
}

/// The shortcuts offered in the menu (a full key recorder is overkill for one command).
struct HotKeyChoice: Identifiable, Hashable {
    let id: String
    let label: String
    let keyCode: UInt32
    let modifiers: UInt32

    static let all: [HotKeyChoice] = [
        HotKeyChoice(id: "opt-space", label: "⌥ Space", keyCode: UInt32(kVK_Space), modifiers: UInt32(optionKey)),
        HotKeyChoice(id: "ctrl-opt-space", label: "⌃⌥ Space", keyCode: UInt32(kVK_Space),
                     modifiers: UInt32(controlKey | optionKey)),
        HotKeyChoice(id: "cmd-shift-space", label: "⌘⇧ Space", keyCode: UInt32(kVK_Space),
                     modifiers: UInt32(cmdKey | shiftKey)),
        HotKeyChoice(id: "opt-d", label: "⌥ D", keyCode: UInt32(kVK_ANSI_D), modifiers: UInt32(optionKey)),
        HotKeyChoice(id: "ctrl-opt-d", label: "⌃⌥ D", keyCode: UInt32(kVK_ANSI_D),
                     modifiers: UInt32(controlKey | optionKey)),
    ]

    static var current: HotKeyChoice { all.first { $0.id == Prefs.hotkey } ?? all[0] }
}
