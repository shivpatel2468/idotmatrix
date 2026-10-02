import AppKit
import SwiftUI

/// Brand colours (warm gradient on graphite, like the studio).
enum Brand {
    static let rose = Color(red: 1.0, green: 0.247, blue: 0.471) // #ff3f78
    static let tangerine = Color(red: 1.0, green: 0.455, blue: 0.098) // #ff7419
    static let gold = Color(red: 1.0, green: 0.8, blue: 0.2) // #ffcc33
    static let ember = Color(red: 1.0, green: 0.282, blue: 0.094) // #ff4818
    static let chassis = Color(red: 0.059, green: 0.059, blue: 0.075) // #0f0f13
    static let chassis2 = Color(red: 0.118, green: 0.118, blue: 0.145) // #1e1e25
    static let line = Color(red: 0.145, green: 0.145, blue: 0.176) // #25252d
    static let ink2 = Color(red: 0.663, green: 0.655, blue: 0.69) // #a9a7b0
    static let ink3 = Color(red: 0.435, green: 0.427, blue: 0.47) // #6f6d78
    static let gradient = LinearGradient(colors: [rose, tangerine, gold], startPoint: .leading, endPoint: .trailing)
}

/// An NSImageView that animates GIFs and scales 32×32 art with nearest-neighbour (crisp LEDs).
struct PixelImage: NSViewRepresentable {
    let image: NSImage?

    func makeNSView(context _: Context) -> NSImageView {
        let v = NSImageView()
        v.animates = true
        v.imageScaling = .scaleProportionallyUpOrDown
        v.wantsLayer = true
        v.layer?.magnificationFilter = .nearest
        v.layer?.minificationFilter = .nearest
        v.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        v.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        return v
    }

    func updateNSView(_ v: NSImageView, context _: Context) {
        if v.image !== image { v.image = image }
    }
}

/// A 32×32 image on a dark bezel with a faint LED dot grid.
struct LEDView: View {
    let image: NSImage?
    var size: CGFloat = 176

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size / 14).fill(Color(white: 0.02))
            PixelImage(image: image).padding(size / 30)
            Canvas { ctx, s in // the gaps between LEDs
                let cell = (s.width - 2 * size / 30) / 32
                guard cell > 3 else { return }
                let o = size / 30
                var p = Path()
                for i in 0 ... 32 {
                    let t = o + CGFloat(i) * cell
                    p.addRect(CGRect(x: t - 0.5, y: o, width: 1, height: s.height - 2 * o))
                    p.addRect(CGRect(x: o, y: t - 0.5, width: s.width - 2 * o, height: 1))
                }
                ctx.fill(p, with: .color(Color(white: 0.02).opacity(0.8)))
            }
            .allowsHitTesting(false)
            RoundedRectangle(cornerRadius: size / 14).strokeBorder(Color.white.opacity(0.08))
        }
        .frame(width: size, height: size)
    }
}

/// The DeskDot mark: a 4×4 dot matrix in the warm gradient.
struct DotMark: View {
    var dot: CGFloat = 5
    private let on: Set<Int> = [0, 3, 5, 6, 9, 10, 12, 15]

    var body: some View {
        VStack(spacing: dot * 0.4) {
            ForEach(0 ..< 4, id: \.self) { y in
                HStack(spacing: dot * 0.4) {
                    ForEach(0 ..< 4, id: \.self) { x in
                        RoundedRectangle(cornerRadius: dot * 0.3)
                            .fill(on.contains(y * 4 + x) ? AnyShapeStyle(Brand.gradient) : AnyShapeStyle(Brand.chassis2))
                            .frame(width: dot, height: dot)
                    }
                }
            }
        }
    }
}

extension NSImage {
    /// Nearest-neighbour upscale (for the menu-bar mini preview).
    func pixelated(to size: NSSize) -> NSImage {
        let out = NSImage(size: size)
        out.lockFocus()
        NSGraphicsContext.current?.imageInterpolation = .none
        draw(in: NSRect(origin: .zero, size: size), from: .zero, operation: .copy, fraction: 1)
        out.unlockFocus()
        return out
    }
}
