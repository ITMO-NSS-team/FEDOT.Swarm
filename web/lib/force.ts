/** A force-directed layout small enough to read. Swarms here are tens of agents, not the
 * thousands a Barnes-Hut tree is for, so repulsion is the plain O(n^2) sum and the whole
 * simulation is a few dozen lines with no dependency. */

export interface Point {
  name: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  /** Pinned by a drag; forces still apply to everyone else. */
  fixed: boolean;
}

export interface Link {
  from: string;
  to: string;
  weight: number;
}

export interface Settings {
  repulsion: number;
  spring: number;
  /** Pull toward the centre, which is what keeps disconnected voices on screen. */
  gravity: number;
  damping: number;
}

export const defaults: Settings = {
  repulsion: 2600,
  spring: 0.035,
  gravity: 0.012,
  damping: 0.86,
};

export class Simulation {
  points = new Map<string, Point>();
  links: Link[] = [];
  settings: Settings;
  /** Drops as the layout settles, so a quiet graph stops burning frames. */
  energy = 1;

  constructor(settings: Settings = defaults) {
    this.settings = settings;
  }

  /** Adds what is new and drops what is gone, keeping positions for everyone who stayed:
   * a round that seats one more voice must not throw the picture away. */
  sync(names: string[], links: Link[]) {
    const seen = new Set(names);
    for (const name of this.points.keys()) {
      if (!seen.has(name)) this.points.delete(name);
    }
    const golden = Math.PI * (3 - Math.sqrt(5));
    names.forEach((name, i) => {
      if (this.points.has(name)) return;
      // a phyllotaxis seed rather than random, so a reload lays the same room out the same way
      const radius = 12 * Math.sqrt(i + 1);
      const angle = i * golden;
      this.points.set(name, {
        name,
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        fixed: false,
      });
      this.energy = 1;
    });
    this.links = links.filter((l) => seen.has(l.from) && seen.has(l.to));
  }

  tick() {
    const { repulsion, spring, gravity, damping } = this.settings;
    const points = [...this.points.values()];
    for (const p of points) {
      p.vx *= damping;
      p.vy *= damping;
    }
    for (let i = 0; i < points.length; i++) {
      for (let j = i + 1; j < points.length; j++) {
        const a = points[i], b = points[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1e-4) {
          // two agents at the same spot have no direction to separate along; deterministic
          // nudge by index keeps the layout reproducible
          dx = (i - j) * 0.01 + 0.01;
          dy = 0.01;
          d2 = dx * dx + dy * dy;
        }
        const force = repulsion / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * force, fy = (dy / d) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
    }
    for (const link of this.links) {
      const a = this.points.get(link.from), b = this.points.get(link.to);
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.hypot(dx, dy) || 1;
      const rest = 120 - 70 * Math.min(1, link.weight);
      const force = (d - rest) * spring * (0.3 + link.weight);
      const fx = (dx / d) * force, fy = (dy / d) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }
    let moved = 0;
    for (const p of points) {
      p.vx -= p.x * gravity;
      p.vy -= p.y * gravity;
      if (p.fixed) {
        p.vx = 0;
        p.vy = 0;
        continue;
      }
      p.x += p.vx;
      p.y += p.vy;
      moved += Math.abs(p.vx) + Math.abs(p.vy);
    }
    this.energy = points.length ? moved / points.length : 0;
  }

  /** Bounding box with a margin, for fitting the drawing into a viewBox. */
  extent(margin = 60) {
    const points = [...this.points.values()];
    if (!points.length) return { x: -100, y: -100, width: 200, height: 200 };
    const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
    const minX = Math.min(...xs) - margin, maxX = Math.max(...xs) + margin;
    const minY = Math.min(...ys) - margin, maxY = Math.max(...ys) + margin;
    return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
  }
}
