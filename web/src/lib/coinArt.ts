/**
 * The silver coin: reeded edge, a face whose highlight slides as it turns, a five-dot emblem and a glint
 * (`angle` 0 = face on, π/2 = edge on). Shared by the Coin Gate intro and the casino key (components/CoinDrop.tsx).
 */
export function drawSilverCoin(o: CanvasRenderingContext2D, x: number, y: number, R: number, angle: number, alpha: number) {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  const ax = Math.abs(c);
  const thick = R * 0.17;
  const rx = Math.max(thick * 0.5, R * ax);
  const ew = thick * Math.abs(s);
  const side = Math.sign(s * c) || 1;
  o.globalAlpha = alpha;
  // the reeded edge
  const eg = o.createLinearGradient(0, y - R, 0, y + R);
  eg.addColorStop(0, "#d8dce1");
  eg.addColorStop(0.5, "#7e868f");
  eg.addColorStop(1, "#4b525a");
  o.fillStyle = eg;
  o.beginPath();
  o.ellipse(x - side * ew, y, rx, R, 0, 0, Math.PI * 2);
  o.fill();
  const ex0 = Math.min(x, x - side * ew);
  o.fillRect(ex0, y - R, ew, R * 2);
  if (ew > 1.5) {
    o.fillStyle = "rgba(0,0,0,0.28)";
    for (let k = -R * 0.9; k < R * 0.9; k += Math.max(2, R * 0.11)) o.fillRect(ex0, y + k, ew, 1);
  }
  // the face, with a highlight that slides as it turns
  const hl = 0.5 + 0.3 * Math.sin(angle * 2);
  const fg = o.createLinearGradient(x - rx, y - R, x + rx, y + R);
  fg.addColorStop(0, "#5d656f");
  fg.addColorStop(Math.max(0.01, hl - 0.2), "#b9c0c8");
  fg.addColorStop(hl, "#ffffff");
  fg.addColorStop(Math.min(0.99, hl + 0.2), "#c3c9d0");
  fg.addColorStop(1, "#56606a");
  o.fillStyle = fg;
  o.beginPath();
  o.ellipse(x, y, rx, R, 0, 0, Math.PI * 2);
  o.fill();
  if (ax > 0.2) {
    o.lineWidth = Math.max(1, R * 0.06);
    o.strokeStyle = "rgba(60,66,74,0.55)";
    o.beginPath();
    o.ellipse(x, y, rx * 0.84, R * 0.84, 0, 0, Math.PI * 2);
    o.stroke();
    // the emblem: five raised LED dots (a die's five)
    o.fillStyle = "rgba(70,76,86,0.6)";
    for (const [i, j] of [[-1, -1], [1, -1], [0, 0], [-1, 1], [1, 1]] as const) {
      o.beginPath();
      o.ellipse(x + i * R * 0.3 * c, y + j * R * 0.3, R * 0.1 * ax, R * 0.1, 0, 0, Math.PI * 2);
      o.fill();
    }
  }
  if (ax > 0.65) {
    // a glint
    const gx = x - rx * 0.4;
    const gy = y - R * 0.45;
    const gl = ((ax - 0.65) / 0.35) * R * 0.45;
    o.globalAlpha = alpha * 0.9;
    o.fillStyle = "#fff";
    o.beginPath();
    o.moveTo(gx, gy - gl);
    o.lineTo(gx + gl * 0.16, gy);
    o.lineTo(gx, gy + gl);
    o.lineTo(gx - gl * 0.16, gy);
    o.closePath();
    o.moveTo(gx - gl, gy);
    o.lineTo(gx, gy + gl * 0.16);
    o.lineTo(gx + gl, gy);
    o.lineTo(gx, gy - gl * 0.16);
    o.closePath();
    o.fill();
  }
  o.globalAlpha = 1;
}
