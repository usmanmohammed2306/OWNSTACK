/** Screen-space placement only. Geometry and labels confer no host authority. */
export type Rect = { x: number; y: number; width: number; height: number };
export type Label = { id: string; x: number; y: number; width: number; height: number };
export const overlaps = (a: Rect, b: Rect, gap = 0) =>
  a.x < b.x + b.width + gap && a.x + a.width + gap > b.x &&
  a.y < b.y + b.height + gap && a.y + a.height + gap > b.y;

/** Keep every label inside its canvas and leave a real gap between hit targets.
 * Prefer its object anchor; use the closest free screen position when crowded.
 * Null means the viewport physically cannot hold the target, never overlap it.
 */
export function placeLabels(labels: Label[], width: number, height: number, gap = 10, obstacles: Rect[] = []): Record<string, Rect | null> {
  const output: Record<string, Rect | null> = {}, placed: Rect[] = [];
  if (![width, height, gap].every(Number.isFinite) || width <= 0 || height <= 0 || gap < 0) return output;
  for (const label of labels) {
    output[label.id] = null;
    if (![label.x, label.y, label.width, label.height].every(Number.isFinite) || label.width <= 0 || label.height <= 0 ||
        label.width + gap * 2 > width || label.height + gap * 2 > height) continue;
    const left = Math.max(gap, Math.min(width - gap - label.width, label.x - label.width / 2));
    const top = Math.max(gap, Math.min(height - gap - label.height, label.y - label.height / 2));
    const candidates: Rect[] = [{x:left,y:top,width:label.width,height:label.height}];
    // A bounded grid avoids layout loops and remains deterministic during orbit.
    for (let y = gap; y <= height - gap - label.height; y += label.height + gap)
      for (let x = gap; x <= width - gap - label.width; x += label.width + gap)
        candidates.push({x,y,width:label.width,height:label.height});
    candidates.sort((a,b) => Math.hypot(a.x-left,a.y-top)-Math.hypot(b.x-left,b.y-top));
    const free = candidates.find(candidate => placed.every(other => !overlaps(candidate,other,gap)) &&
      obstacles.every(other => !overlaps(candidate,other,gap)));
    if (free) { placed.push(free); output[label.id] = free; }
  }
  return output;
}

/** A hover card stays inside the visible scene instead of covering its inspector. */
export function tooltipPosition(x: number, y: number, bounds: Rect, width = 232, height = 132): Rect {
  const safeWidth = Math.max(1, Math.min(width, bounds.width - 24));
  const safeHeight = Math.max(1, Math.min(height, bounds.height - 24));
  const left = Math.max(bounds.x + 12, Math.min(x - safeWidth / 2, bounds.x + bounds.width - safeWidth - 12));
  const preferred = y + 18 + safeHeight <= bounds.y + bounds.height - 12 ? y + 18 : y - safeHeight - 18;
  return {x:left,y:Math.max(bounds.y+12,Math.min(preferred,bounds.y+bounds.height-safeHeight-12)),width:safeWidth,height:safeHeight};
}
