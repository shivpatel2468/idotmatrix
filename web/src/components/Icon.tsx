import { icons, type LucideProps } from "lucide-react";

const pascal = (s: string) => s.replace(/(^|-)([a-z0-9])/g, (_, __, c: string) => c.toUpperCase());

/**
 * Render a lucide icon by its kebab-case name (what apps declare in Python).
 * `duo`: the duotone style — the outline plus a soft fill of its shapes in the same colour (docs/STUDIO_UI.md, Icons).
 */
export function Icon({ name, duo = false, ...props }: { name: string; duo?: boolean } & LucideProps) {
  const Cmp = (icons as Record<string, React.ComponentType<LucideProps>>)[pascal(name)] ?? icons.Square;
  return duo
    ? <Cmp strokeWidth={1.75} fill="currentColor" fillOpacity={0.2} {...props} />
    : <Cmp strokeWidth={1.6} {...props} />;
}

/** The tint family of an icon tile: an app category, or a named accent. Colours per theme live in index.css. */
export type Tone =
  | "time" | "data" | "media" | "creative" | "ambient" | "productivity" | "pets" | "games" | "casino" | "device"
  | "ember" | "gold" | "ok" | "info" | "neutral";

/**
 * A duotone glyph on a tinted, softly lit tile — the studio's "detailed icon" (app rows, presets, menus, quick
 * controls). `solid` fills the tile with the tint (selected / playing).
 */
export function IconTile({ name, tone = "ember", size = 36, glyph, solid = false, className = "" }: {
  name: string;
  tone?: Tone | string;
  size?: number;
  glyph?: number;
  solid?: boolean;
  className?: string;
}) {
  return (
    <span className={`icon-tile ${className}`} data-tone={tone} data-solid={solid || undefined} aria-hidden
      style={{ width: size, height: size, borderRadius: Math.round(size * 0.3) }}>
      <Icon name={name} duo size={glyph ?? Math.round(size * 0.5)} />
    </span>
  );
}

export const CATEGORY_LABEL: Record<string, string> = {
  time: "Time",
  data: "Live data",
  media: "Media",
  creative: "Create",
  ambient: "Ambient",
  productivity: "Focus & agents",
  pets: "Pets & characters",
  games: "Games",
  casino: "Casino",
  device: "Panel",
};

/** One icon per category (row headers, chips). */
export const CATEGORY_ICON: Record<string, string> = {
  time: "clock-3",
  data: "activity",
  media: "image",
  creative: "palette",
  ambient: "sparkles",
  productivity: "target",
  pets: "paw-print",
  games: "gamepad-2",
  casino: "dices",
  device: "cpu",
};

export const CATEGORY_ORDER = ["time", "data", "media", "pets", "games", "casino", "creative", "productivity", "ambient", "device"];
