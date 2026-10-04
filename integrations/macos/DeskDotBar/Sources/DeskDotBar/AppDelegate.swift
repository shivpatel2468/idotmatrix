import AppKit
import Combine
import SwiftUI

/// The menu-bar item (a mini live view of the panel + the app's name), its popover and the global hotkey.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let store = DeskDotStore()
    private var statusItem: NSStatusItem!
    private let popover = NSPopover()
    private var commandBar: CommandBarController!
    private var hotKey: HotKey?
    private var bag = Set<AnyCancellable>()

    func applicationDidFinishLaunching(_: Notification) {
        commandBar = CommandBarController(store: store)

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = placeholderIcon()
            button.imagePosition = .imageLeading
            button.action = #selector(togglePopover(_:))
            button.target = self
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }

        popover.behavior = .transient
        popover.animates = true
        popover.contentViewController = NSHostingController(rootView: MenuView(
            store: store,
            openCommandBar: { [weak self] in
                self?.popover.performClose(nil)
                self?.commandBar.show()
            },
            hotkeyChanged: { [weak self] in self?.registerHotKey() }
        ).preferredColorScheme(.dark))

        store.$frame.combineLatest(store.$state, store.$online)
            .receive(on: RunLoop.main)
            .sink { [weak self] frame, _, online in self?.updateStatusItem(frame: frame, online: online) }
            .store(in: &bag)

        registerHotKey()
        store.start()
    }

    private func registerHotKey() {
        let choice = HotKeyChoice.current
        hotKey?.unregister()
        hotKey = HotKey(keyCode: choice.keyCode, modifiers: choice.modifiers) { [weak self] in
            self?.commandBar.toggle()
        }
        if hotKey?.registered != true {
            store.flash("\(choice.label) is taken by another app — pick another in Settings")
        }
    }

    private func updateStatusItem(frame: NSImage?, online: Bool) {
        guard let button = statusItem.button else { return }
        if online, let frame {
            button.image = frame.pixelated(to: NSSize(width: 18, height: 18))
        } else {
            button.image = placeholderIcon()
        }
        let name = online ? (store.currentApp?.name ?? "") : ""
        button.title = name.isEmpty ? "" : " " + (name.count > 18 ? String(name.prefix(17)) + "…" : name)
        button.toolTip = online ? "DeskDot · \(name)" : "DeskDot · engine offline"
    }

    private func placeholderIcon() -> NSImage {
        let img = NSImage(systemSymbolName: "square.grid.4x3.fill", accessibilityDescription: "DeskDot")
            ?? NSImage(size: NSSize(width: 18, height: 18))
        img.isTemplate = true
        return img
    }

    @objc private func togglePopover(_ sender: NSStatusBarButton) {
        if popover.isShown {
            popover.performClose(sender)
            store.interactive = commandBar.isVisible
        } else {
            store.interactive = true
            popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }
}
