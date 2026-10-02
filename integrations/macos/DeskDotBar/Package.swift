// swift-tools-version:5.9
// DeskDot Bar: a macOS menu-bar companion + Spotlight-style command bar for the DeskDot engine (docs/LAUNCHERS.md).
import PackageDescription

let package = Package(
    name: "DeskDotBar",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "DeskDotBar",
            path: "Sources/DeskDotBar",
            linkerSettings: [.linkedFramework("Carbon")]
        ),
    ]
)
