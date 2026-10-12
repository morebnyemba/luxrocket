/**
 * Cinematic journey scene (doc 14 §4). Purely presentational: it renders whatever multiplier
 * the HUD shows and never knows the crash point before ROUND_CRASHED arrives.
 *
 * Everything is procedural (geometry, canvas textures, particles) so the first playable scene
 * needs no downloaded assets; authored models/textures replace pieces later (doc 18 §5).
 */
import * as THREE from "three";
import { altitudeFor, MILESTONES } from "./journey";
import { TIERS, lower, type Tier } from "./quality";

export interface FrameInput {
  phase: "WAITING" | "BETTING_OPEN" | "BETTING_CLOSED" | "FLYING" | "CRASHED" | "VOIDED";
  multiplierX10000: number;
  reducedMotion: boolean;
}

const SKY = new THREE.Color("#3a6fb5");
const SPACE = new THREE.Color("#05060a");

export class RocketScene {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(55, 1, 0.1, 6_000);
  private readonly rocket = new THREE.Group();
  private readonly flame: THREE.Mesh;
  private stars!: THREE.Points;
  private exhaust!: THREE.Points;
  private exhaustVel!: Float32Array;
  private exhaustLife!: Float32Array;
  private explosion: THREE.Points | null = null;
  private explosionVel: Float32Array | null = null;
  private explosionAge = 0;
  private lastPhase: FrameInput["phase"] = "WAITING";
  private lastTime = performance.now();
  private frameTimes: number[] = [];
  private tier: Tier;
  private shake = 0;
  private disposed = false;
  contextLost = false;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    tier: Tier,
  ) {
    this.tier = tier;
    const settings = TIERS[tier];
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: settings.antialias,
      powerPreference: tier === "low" ? "low-power" : "high-performance",
      alpha: false,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, settings.dpr));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    canvas.addEventListener("webglcontextlost", this.onContextLost, false);

    this.scene.background = SKY.clone();
    this.scene.fog = new THREE.Fog(SKY.clone(), 200, 1_500);

    this.scene.add(new THREE.HemisphereLight(0xcfe3ff, 0x1a1a2a, 0.9));
    const sun = new THREE.DirectionalLight(0xffffff, 2.2);
    sun.position.set(80, 120, 60);
    this.scene.add(sun);

    this.buildEarth(settings.sphereSegments);
    this.buildPlanets(settings.sphereSegments);
    this.buildStars(settings.stars);
    this.flame = this.buildRocket();
    this.buildExhaust(settings.exhaust);

    this.camera.position.set(0, 4, 24);
  }

  // ---- construction ----------------------------------------------------------------------

  private buildEarth(segments: number): void {
    const earth = new THREE.Mesh(
      new THREE.SphereGeometry(600, segments * 2, segments * 2),
      new THREE.MeshStandardMaterial({ map: earthTexture(), roughness: 0.9 }),
    );
    earth.position.set(0, -606, 0);
    earth.rotation.z = 0.3;
    this.scene.add(earth);

    const atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(615, segments * 2, segments),
      new THREE.MeshBasicMaterial({ color: 0x6fb6ff, transparent: true, opacity: 0.18, side: THREE.BackSide }),
    );
    atmosphere.position.copy(earth.position);
    this.scene.add(atmosphere);

    const pad = new THREE.Mesh(
      new THREE.CylinderGeometry(4, 5, 1.2, 24),
      new THREE.MeshStandardMaterial({ color: 0x4b5160, metalness: 0.4, roughness: 0.6 }),
    );
    pad.position.y = -0.6;
    this.scene.add(pad);
  }

  private buildPlanets(segments: number): void {
    const specs: Record<string, { radius: number; color: string; x: number; texture?: THREE.Texture; ring?: boolean }> = {
      moon: { radius: 10, color: "#b9b9c0", x: -70 },
      mars: { radius: 14, color: "#c1440e", x: 55 },
      jupiter: { radius: 45, color: "#d8b48a", x: -120, texture: bandedTexture(["#d9b38c", "#b9875a", "#f0dcc0", "#a96f45"]) },
      saturn: { radius: 34, color: "#e3cf9f", x: 110, texture: bandedTexture(["#e8d6a8", "#cdb27c", "#f3e6c4"]), ring: true },
    };
    for (const m of MILESTONES) {
      const spec = specs[m.key];
      if (!spec) continue;
      const planet = new THREE.Mesh(
        new THREE.SphereGeometry(spec.radius, segments, segments),
        new THREE.MeshStandardMaterial({ color: spec.texture ? 0xffffff : spec.color, map: spec.texture ?? null, roughness: 1 }),
      );
      // Far behind the flight path: scenery the rocket passes, never something it reaches.
      planet.position.set(spec.x, altitudeFor(m.at), -spec.radius * 4 - 40);
      this.scene.add(planet);
      if (spec.ring) {
        const ring = new THREE.Mesh(
          new THREE.RingGeometry(spec.radius * 1.4, spec.radius * 2.3, 96),
          new THREE.MeshBasicMaterial({ color: 0xd8c08a, side: THREE.DoubleSide, transparent: true, opacity: 0.65 }),
        );
        ring.rotation.x = Math.PI / 2.4;
        ring.position.copy(planet.position);
        this.scene.add(ring);
      }
    }
  }

  private buildStars(count: number): void {
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 600 + Math.random() * 1_400;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.cos(phi);
      positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    this.stars = new THREE.Points(
      geometry,
      new THREE.PointsMaterial({ color: 0xffffff, size: 2, sizeAttenuation: false, transparent: true, opacity: 0 }),
    );
    this.scene.add(this.stars);
  }

  private buildRocket(): THREE.Mesh {
    const white = new THREE.MeshStandardMaterial({ color: 0xf2f4f8, metalness: 0.3, roughness: 0.35 });
    const gold = new THREE.MeshStandardMaterial({ color: 0xf5c04a, metalness: 0.7, roughness: 0.3 });
    const dark = new THREE.MeshStandardMaterial({ color: 0x1b1f2a, metalness: 0.5, roughness: 0.5 });

    const body = new THREE.Mesh(new THREE.CylinderGeometry(1, 1.15, 6, 32), white);
    body.position.y = 3.6;
    const nose = new THREE.Mesh(new THREE.ConeGeometry(1, 2.4, 32), gold);
    nose.position.y = 7.8;
    const band = new THREE.Mesh(new THREE.CylinderGeometry(1.02, 1.02, 0.35, 32), gold);
    band.position.y = 5.4;
    const porthole = new THREE.Mesh(
      new THREE.SphereGeometry(0.38, 16, 16),
      new THREE.MeshStandardMaterial({ color: 0x4cc9f0, emissive: 0x1a6f8f, metalness: 0.2, roughness: 0.1 }),
    );
    porthole.position.set(0, 4.6, 0.95);
    const bell = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 0.85, 0.9, 24), dark);
    bell.position.y = 0.2;
    this.rocket.add(body, nose, band, porthole, bell);

    for (let i = 0; i < 3; i++) {
      const fin = new THREE.Mesh(new THREE.BoxGeometry(0.12, 1.8, 1.4), gold);
      const angle = (i / 3) * Math.PI * 2;
      fin.position.set(Math.cos(angle) * 1.15, 1.4, Math.sin(angle) * 1.15);
      fin.rotation.y = -angle;
      this.rocket.add(fin);
    }

    const flame = new THREE.Mesh(
      new THREE.ConeGeometry(0.6, 2.6, 16, 1, true),
      new THREE.MeshBasicMaterial({ color: 0xffb347, transparent: true, opacity: 0.85, blending: THREE.AdditiveBlending }),
    );
    flame.rotation.x = Math.PI;
    flame.position.y = -1.3;
    flame.visible = false;
    this.rocket.add(flame);
    this.scene.add(this.rocket);
    return flame;
  }

  private buildExhaust(count: number): void {
    const positions = new Float32Array(count * 3).fill(-9999);
    this.exhaustVel = new Float32Array(count * 3);
    this.exhaustLife = new Float32Array(count);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    this.exhaust = new THREE.Points(
      geometry,
      new THREE.PointsMaterial({
        color: 0xffa040,
        size: 0.9,
        transparent: true,
        opacity: 0.75,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    this.scene.add(this.exhaust);
  }

  private explode(at: THREE.Vector3, count: number): void {
    const positions = new Float32Array(count * 3);
    this.explosionVel = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      positions.set([at.x, at.y + 3, at.z], i * 3);
      const dir = new THREE.Vector3(Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5).normalize();
      const speed = 8 + Math.random() * 18;
      this.explosionVel.set([dir.x * speed, dir.y * speed, dir.z * speed], i * 3);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    this.explosion = new THREE.Points(
      geometry,
      new THREE.PointsMaterial({ color: 0xff4d5e, size: 1.2, transparent: true, opacity: 1, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    this.explosionAge = 0;
    this.scene.add(this.explosion);
  }

  private clearExplosion(): void {
    if (!this.explosion) return;
    this.scene.remove(this.explosion);
    this.explosion.geometry.dispose();
    (this.explosion.material as THREE.Material).dispose();
    this.explosion = null;
  }

  // ---- per frame ---------------------------------------------------------------------------

  resize(width: number, height: number): void {
    if (width <= 0 || height <= 0) return;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  render(input: FrameInput): void {
    if (this.disposed || this.contextLost) return;
    const now = performance.now();
    const dt = Math.min((now - this.lastTime) / 1000, 0.1);
    this.lastTime = now;
    this.govern(dt);

    const flying = input.phase === "FLYING";
    const crashed = input.phase === "CRASHED" || input.phase === "VOIDED";
    if (input.phase !== this.lastPhase) {
      if (crashed && this.lastPhase === "FLYING") {
        this.explode(this.rocket.position, input.reducedMotion ? 120 : TIERS[this.tier].exhaust * 2);
        this.shake = input.reducedMotion ? 0 : 1;
      }
      if (input.phase === "BETTING_OPEN") this.clearExplosion();
      this.lastPhase = input.phase;
    }

    const altitude = flying || crashed ? altitudeFor(input.multiplierX10000) : 0;
    this.rocket.visible = !crashed;
    this.rocket.position.y = altitude;
    this.rocket.rotation.z = flying && !input.reducedMotion ? Math.sin(now / 600) * 0.03 : 0;
    this.flame.visible = flying;
    if (flying) this.flame.scale.setScalar(0.9 + Math.random() * 0.25);

    // Sky fades to space with altitude.
    const t = Math.min(altitude / 45, 1);
    const sky = SKY.clone().lerp(SPACE, t);
    (this.scene.background as THREE.Color).copy(sky);
    (this.scene.fog as THREE.Fog).color.copy(sky);
    (this.stars.material as THREE.PointsMaterial).opacity = Math.min(1, t * 1.4);
    this.stars.position.y = this.rocket.position.y * 0.9;

    this.updateExhaust(dt, flying);
    this.updateExplosion(dt);

    // Follow camera with critically damped smoothing; gentle shake on crash.
    const target = new THREE.Vector3(6, altitude + 5, 26);
    this.camera.position.lerp(target, 1 - Math.exp(-dt * 4));
    if (this.shake > 0) {
      this.camera.position.x += (Math.random() - 0.5) * this.shake;
      this.camera.position.y += (Math.random() - 0.5) * this.shake;
      this.shake = Math.max(0, this.shake - dt * 1.5);
    }
    // Look above the rocket so it sits in the lower third, leaving the multiplier clear.
    this.camera.lookAt(0, altitude + 9, 0);
    this.renderer.render(this.scene, this.camera);
  }

  private updateExhaust(dt: number, emitting: boolean): void {
    const pos = this.exhaust.geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = pos.array as Float32Array;
    const count = this.exhaustLife.length;
    const base = this.rocket.position;
    for (let i = 0; i < count; i++) {
      this.exhaustLife[i]! -= dt;
      if (this.exhaustLife[i]! <= 0) {
        if (emitting) {
          this.exhaustLife[i] = 0.4 + Math.random() * 0.6;
          arr[i * 3] = base.x + (Math.random() - 0.5) * 0.8;
          arr[i * 3 + 1] = base.y - 1.2;
          arr[i * 3 + 2] = base.z + (Math.random() - 0.5) * 0.8;
          this.exhaustVel[i * 3] = (Math.random() - 0.5) * 3;
          this.exhaustVel[i * 3 + 1] = -12 - Math.random() * 10;
          this.exhaustVel[i * 3 + 2] = (Math.random() - 0.5) * 3;
        } else {
          arr[i * 3 + 1] = -9999;
        }
        continue;
      }
      arr[i * 3] = arr[i * 3]! + this.exhaustVel[i * 3]! * dt;
      arr[i * 3 + 1] = arr[i * 3 + 1]! + this.exhaustVel[i * 3 + 1]! * dt;
      arr[i * 3 + 2] = arr[i * 3 + 2]! + this.exhaustVel[i * 3 + 2]! * dt;
    }
    pos.needsUpdate = true;
  }

  private updateExplosion(dt: number): void {
    if (!this.explosion || !this.explosionVel) return;
    this.explosionAge += dt;
    const pos = this.explosion.geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = pos.array as Float32Array;
    for (let i = 0; i < arr.length; i++) arr[i] = arr[i]! + this.explosionVel[i]! * dt;
    pos.needsUpdate = true;
    (this.explosion.material as THREE.PointsMaterial).opacity = Math.max(0, 1 - this.explosionAge / 1.6);
  }

  /** Runtime governor: drop pixel ratio when p90 frame time exceeds 33 ms (doc 14 §4.4). */
  private govern(dt: number): void {
    this.frameTimes.push(dt * 1000);
    if (this.frameTimes.length < 120) return;
    const sorted = [...this.frameTimes].sort((a, b) => a - b);
    const p90 = sorted[Math.floor(sorted.length * 0.9)] ?? 0;
    this.frameTimes = [];
    if (p90 > 33 && this.tier !== "low") {
      this.tier = lower(this.tier);
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, TIERS[this.tier].dpr));
    }
  }

  private onContextLost = (event: Event): void => {
    event.preventDefault();
    this.contextLost = true;
  };

  dispose(): void {
    this.disposed = true;
    this.canvas.removeEventListener("webglcontextlost", this.onContextLost);
    this.clearExplosion();
    this.scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      mesh.geometry?.dispose();
      const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(material)) material.forEach((m) => m.dispose());
      else material?.dispose();
    });
    this.renderer.dispose();
  }
}

// ---- procedural textures ---------------------------------------------------------------------

function earthTexture(): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 256;
  const g = c.getContext("2d")!;
  g.fillStyle = "#1d4f91";
  g.fillRect(0, 0, c.width, c.height);
  for (let i = 0; i < 70; i++) {
    g.fillStyle = Math.random() > 0.3 ? "#3b7d3a" : "#a8915c";
    g.beginPath();
    g.ellipse(Math.random() * 512, 40 + Math.random() * 176, 8 + Math.random() * 40, 5 + Math.random() * 22, Math.random() * 3, 0, Math.PI * 2);
    g.fill();
  }
  g.globalAlpha = 0.35;
  g.fillStyle = "#ffffff";
  for (let i = 0; i < 60; i++) {
    g.beginPath();
    g.ellipse(Math.random() * 512, Math.random() * 256, 10 + Math.random() * 50, 3 + Math.random() * 8, 0, 0, Math.PI * 2);
    g.fill();
  }
  const texture = new THREE.CanvasTexture(c);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function bandedTexture(colors: string[]): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = 16;
  c.height = 256;
  const g = c.getContext("2d")!;
  let y = 0;
  while (y < 256) {
    const h = 6 + Math.random() * 22;
    g.fillStyle = colors[Math.floor(Math.random() * colors.length)] ?? "#ccc";
    g.fillRect(0, y, 16, h);
    y += h;
  }
  const texture = new THREE.CanvasTexture(c);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}
