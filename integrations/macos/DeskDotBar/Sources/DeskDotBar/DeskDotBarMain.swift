import AppKit

/// A menu-bar-only app: no Dock icon, no main window (the .app bundle also sets LSUIElement).
@main
enum DeskDotBarMain {
    @MainActor
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        withExtendedLifetime(delegate) { app.run() }
    }
}
