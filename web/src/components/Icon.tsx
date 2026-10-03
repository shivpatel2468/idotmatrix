import { icons, type LucideProps } from "lucide-react";

const pascal = (s: string) => s.replace(/(^|-)([a-z0-9])/g, (_, __, c: string) => c.toUpperCase());

/** Render a lucide icon by its kebab-case name (what apps declare in Python). */
export function Icon({ name, ...props }: { name: string } & LucideProps) {
  const Cmp = (icons as Record<string, React.ComponentType<LucideProps>>)[pascal(name)] ?? icons.Square;
  return <Cmp strokeWidth={1.6} {...props} />;
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

export const CATEGORY_ORDER = ["time", "data", "media", "pets", "games", "casino", "creative", "productivity", "ambient", "device"];
