/**
 * Release notes (WHATS_NEW.md style) before they are drawn (components/Updates.tsx → ReleaseNotes). Pure, so
 * tests/js/release_notes.test.mjs runs it in node.
 */

/** A bullet's wrapped lines (indented, not a bullet or a heading themselves) belong to it: WHATS_NEW.md wraps long
 *  "Before:" / "Now:" items over several lines, and without this each wrap rendered as a stray paragraph. */
export function joinContinuations(lines: string[]): string[] {
  const out: string[] = [];
  let inBullet = false;
  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*]\s+/.test(line);
    if (!line.trim()) {
      inBullet = false;
      out.push(line);
    } else if (!bullet && inBullet && /^\s+\S/.test(line) && !/^\s*#/.test(line)) {
      out[out.length - 1] += " " + line.trim();
    } else {
      inBullet = bullet;
      out.push(line);
    }
  }
  return out;
}
