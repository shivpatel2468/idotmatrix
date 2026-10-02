import AppKit
import SwiftUI

/// A floating, non-activating panel (like Spotlight): it takes the keyboard without pulling the frontmost app's
/// windows forward, sits above full-screen apps, and hides when it loses key status.
final class CommandPanel: NSPanel {
    var onResign: (() -> Void)?

    init<Content: View>(rootView: Content) {
        super.init(
            contentRect: NSRect(x: 0, y: 0, width: 780, height: 480),
            styleMask: [.nonactivatingPanel, .titled, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        isFloatingPanel = true
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
        titleVisibility = .hidden
        titlebarAppearsTransparent = true
        isMovableByWindowBackground = true
        hidesOnDeactivate = false
        isReleasedWhenClosed = false
        backgroundColor = .clear
        isOpaque = false
        hasShadow = true
        for b in [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton] {
            standardWindowButton(b)?.isHidden = true
        }
        let host = NSHostingView(rootView: rootView)
        host.wantsLayer = true
        host.layer?.backgroundColor = NSColor.clear.cgColor
        contentView = host
    }

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    override func resignKey() {
        super.resignKey()
        onResign?()
    }

    /// Centre horizontally on the screen with the mouse, a fifth of the way down (where Spotlight sits).
    func placeOnActiveScreen() {
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { NSMouseInRect(mouse, $0.frame, false) } ?? NSScreen.main
        guard let vf = screen?.visibleFrame else { return center() }
        let x = vf.midX - frame.width / 2
        let y = vf.maxY - vf.height * 0.2 - frame.height
        setFrameOrigin(NSPoint(x: x.rounded(), y: max(vf.minY, y).rounded()))
    }
}

/// Owns the panel, its key monitor and show/hide.
@MainActor
final class CommandBarController {
    let model: CommandModel
    private lazy var panel: CommandPanel = {
        let p = CommandPanel(rootView: CommandBarView(model: model, store: model.store))
        p.onResign = { [weak self] in self?.hide() }
        return p
    }()
    private var monitor: Any?

    init(store: DeskDotStore) {
        model = CommandModel(store: store)
        model.close = { [weak self] in self?.hide() }
    }

    var isVisible: Bool { panel.isVisible }

    func toggle() { isVisible ? hide() : show() }

    func show() {
        model.store.interactive = true
        PreviewCache.shared.clear()
        panel.placeOnActiveScreen()
        panel.makeKeyAndOrderFront(nil)
        model.selection = 0
        model.focusToken += 1
        if monitor == nil {
            monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
                guard let self, event.window === self.panel else { return event }
                return self.model.handleKey(event) ? nil : event
            }
        }
    }

    func hide() {
        guard panel.isVisible else { return }
        panel.orderOut(nil)
        model.store.interactive = false
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
    }
}
