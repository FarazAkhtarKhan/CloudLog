// The 3D model of the pipeline: white "architect's model" parts on a table, packets for log lines.
// Imperative three.js, kept out of React. LiveModel.jsx drives it with play() / pending() / settle().
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";

const COLOR = {
  model: 0xfbfcfd,
  edge: 0x9ba6b5,
  ink: 0x1b2430,
  wire: 0xb3bcc8,
  grid: 0xd3d9e1,
  CRITICAL: { fill: 0xfbe5e8, edge: 0xc8102e },
  ERROR: { fill: 0xfbebe1, edge: 0xc4511c },
  WARNING: { fill: 0xf8efcf, edge: 0xd9a300 },
  INFO: { fill: 0xe1eff4, edge: 0x23708d },
};

// Layout on the table (x = flow direction). Top row: ingestion. Bottom row: dashboard queries.
const ROW_IN = -2.9;
const ROW_Q = 3.3;
const POS = {
  source: new THREE.Vector3(-9, 0, ROW_IN),
  s3: new THREE.Vector3(-4.5, 0, ROW_IN),
  lambda: new THREE.Vector3(0, 0, ROW_IN),
  dynamo: new THREE.Vector3(4.8, 0, 0.1),
  sns: new THREE.Vector3(9.4, 0, ROW_IN),
  oncall: new THREE.Vector3(9.4, 0, ROW_Q),
  dashboard: new THREE.Vector3(-9, 0, ROW_Q),
  gateway: new THREE.Vector3(-4.5, 0, ROW_Q),
  api: new THREE.Vector3(0, 0, ROW_Q),
};
const BOUNDS = new THREE.Box3(new THREE.Vector3(-10.2, 0, -3.9), new THREE.Vector3(10.4, 2.4, 4.7));
const v = (x, y, z) => new THREE.Vector3(x, y, z);
const Y = 0.05; // wires lie on the table

const WIRES = {
  upload: { points: [v(-8.1, Y, ROW_IN), v(-5.45, Y, ROW_IN)] },
  trigger: { points: [v(-3.6, Y, ROW_IN), v(-0.8, Y, ROW_IN)] },
  store: { points: [v(0.8, Y, ROW_IN + 0.3), v(3.9, Y, -0.55)] },
  notify: { points: [v(9.4, Y, ROW_IN + 0.6), v(9.4, Y, ROW_Q - 0.25)] },
  request: { points: [v(-8.0, Y, ROW_Q), v(-5.3, Y, ROW_Q)], dashed: true },
  invoke: { points: [v(-3.7, Y, ROW_Q), v(-0.7, Y, ROW_Q)], dashed: true },
  query: { points: [v(0.7, Y, ROW_Q - 0.3), v(3.9, Y, 0.75)], dashed: true },
};
const ALERT_ARC = new THREE.QuadraticBezierCurve3(v(0, 1.62, ROW_IN), v(4.7, 5.4, ROW_IN), v(9.4, 1.95, ROW_IN));

const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function createWorld(host, { onPick } = {}) {
  // ---------------------------------------------------------------- renderer, camera, light
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.domElement.className = "scene-canvas";
  host.appendChild(renderer.domElement);

  const labels = new CSS2DRenderer();
  labels.domElement.className = "scene-labels";
  host.appendChild(labels.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 200);
  const target = BOUNDS.getCenter(new THREE.Vector3()).setY(0.7);
  camera.position.copy(target).add(new THREE.Vector3().setFromSphericalCoords(40, 0.86, 0.3));
  camera.lookAt(target);

  scene.add(new THREE.HemisphereLight(0xffffff, 0xb9c3cf, 2.1));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.position.set(-7, 16, 9);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.radius = 4;
  Object.assign(sun.shadow.camera, { left: -15, right: 15, top: 12, bottom: -12, near: 1, far: 50 });
  scene.add(sun);

  const table = new THREE.Mesh(new THREE.PlaneGeometry(60, 40), new THREE.ShadowMaterial({ opacity: 0.11 }));
  table.rotation.x = -Math.PI / 2;
  table.receiveShadow = true;
  scene.add(table);
  const grid = new THREE.GridHelper(30, 30, COLOR.grid, COLOR.grid);
  grid.position.set(0.1, 0.002, 0.4);
  grid.material.transparent = true;
  grid.material.opacity = 0.55;
  scene.add(grid);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(target);
  Object.assign(controls, {
    enableZoom: false, enablePan: false, enableDamping: true, dampingFactor: 0.08, rotateSpeed: 0.55,
    minAzimuthAngle: -0.35, maxAzimuthAngle: 0.95, minPolarAngle: 0.55, maxPolarAngle: 1.25,
  });
  // On touch screens the model is for looking at; dragging would trap page scrolling.
  if (window.matchMedia("(pointer: coarse)").matches) {
    controls.enabled = false;
    renderer.domElement.style.touchAction = "pan-x pan-y";
  }
  controls.update();
  controls.saveState();

  // ---------------------------------------------------------------- colour fades
  const fades = new Set(); // { color, target }
  const fadeTo = (material, hex) => {
    material.userData.fade ||= { color: material.color, target: new THREE.Color(hex) };
    material.userData.fade.target.set(hex);
    fades.add(material.userData.fade);
  };

  // ---------------------------------------------------------------- parts
  const parts = {}; // `${node}` or `${node}.${part}` -> { mats, lines, state }
  const pickable = [];
  const nodes = {};

  function solid(node, part, geometry, material) {
    const mat = material || new THREE.MeshStandardMaterial({ color: COLOR.model, roughness: 0.85 });
    const mesh = new THREE.Mesh(geometry, mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    const line = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 30), new THREE.LineBasicMaterial({ color: COLOR.edge }));
    mesh.add(line);
    mesh.userData.node = node;
    pickable.push(mesh);
    for (const key of part ? [node, `${node}.${part}`] : [node]) {
      parts[key] ||= { mats: [], lines: [], state: "idle" };
      parts[key].mats.push(mat);
      parts[key].lines.push(line.material);
    }
    return mesh;
  }

  function node(id, build, labelOffset = v(0, 0, 1.25)) {
    const group = new THREE.Group();
    group.position.copy(POS[id]);
    build(group, (geometry, part, material) => solid(id, part, geometry, material));
    const anchor = document.createElement("div");
    anchor.className = "scene-anchor";
    const label = new CSS2DObject(anchor);
    label.position.copy(labelOffset);
    group.add(label);
    scene.add(group);
    nodes[id] = { group, anchor };
  }

  node("source", (g, s) => {
    const box = s(new THREE.BoxGeometry(1.5, 1.2, 1.1));
    box.position.y = 0.6;
    g.add(box);
    for (let i = 0; i < 3; i++) {
      const slot = s(new THREE.BoxGeometry(1.1, 0.06, 0.02));
      slot.position.set(0, 0.32 + i * 0.28, 0.56);
      g.add(slot);
    }
  });

  node("s3", (g, s) => {
    const wall = s(new THREE.CylinderGeometry(0.95, 0.72, 1.3, 40, 1, true),
      undefined, new THREE.MeshStandardMaterial({ color: COLOR.model, roughness: 0.85, side: THREE.DoubleSide }));
    wall.position.y = 0.65;
    const floor = s(new THREE.CircleGeometry(0.72, 40));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = 0.02;
    const rim = s(new THREE.TorusGeometry(0.95, 0.05, 8, 48));
    rim.rotation.x = Math.PI / 2;
    rim.position.y = 1.3;
    g.add(wall, floor, rim);
  });

  let ring; // spins while the processor runs
  node("lambda", (g, s) => {
    const box = s(new THREE.BoxGeometry(1.5, 1.5, 1.5));
    box.position.y = 0.75;
    g.add(box);
    ring = new THREE.Mesh(new THREE.TorusGeometry(1.25, 0.035, 8, 64, Math.PI * 1.4), new THREE.MeshBasicMaterial({ color: COLOR.ink }));
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.75;
    ring.visible = false;
    g.add(ring);
  });

  const DISC = { events: 0.21, incidents: 0.75, runs: 1.29 };
  node("dynamo", (g, s) => {
    for (const [part, y] of Object.entries(DISC)) {
      const disc = s(new THREE.CylinderGeometry(1.1, 1.1, 0.42, 48), part);
      disc.position.y = y;
      g.add(disc);
    }
  }, v(0, 0, 1.6));

  let beacon;
  node("sns", (g, s) => {
    const base = s(new THREE.CylinderGeometry(0.55, 0.62, 0.18, 32));
    base.position.y = 0.09;
    const pole = s(new THREE.CylinderGeometry(0.09, 0.09, 1.5, 12));
    pole.position.y = 0.9;
    beacon = s(new THREE.SphereGeometry(0.42, 32, 16), "beacon",
      new THREE.MeshStandardMaterial({ color: COLOR.model, roughness: 0.6, emissive: COLOR.CRITICAL.edge, emissiveIntensity: 0 }));
    beacon.position.y = 1.95;
    g.add(base, pole, beacon);
  });

  node("oncall", (g, s) => {
    const phone = s(new THREE.BoxGeometry(0.85, 1.45, 0.16));
    phone.position.y = 0.78;
    phone.rotation.x = -0.12;
    const screen = s(new THREE.PlaneGeometry(0.66, 1.1), "screen");
    screen.position.set(0, 0.8, 0.087);
    screen.rotation.x = -0.12;
    g.add(phone, screen);
  });

  node("dashboard", (g, s) => {
    const panel = s(new THREE.BoxGeometry(1.9, 1.15, 0.1));
    panel.position.y = 1.2;
    const stand = s(new THREE.BoxGeometry(0.14, 0.7, 0.14));
    stand.position.y = 0.35;
    const foot = s(new THREE.BoxGeometry(0.8, 0.06, 0.5));
    foot.position.y = 0.03;
    g.add(panel, stand, foot);
  });

  node("gateway", (g, s) => {
    for (const x of [-0.65, 0.65]) {
      const pillar = s(new THREE.BoxGeometry(0.3, 1.4, 0.4));
      pillar.position.set(x, 0.7, 0);
      g.add(pillar);
    }
    const lintel = s(new THREE.BoxGeometry(1.7, 0.28, 0.5));
    lintel.position.y = 1.54;
    g.add(lintel);
  });

  node("api", (g, s) => {
    const box = s(new THREE.BoxGeometry(1.3, 1.3, 1.3));
    box.position.y = 0.65;
    g.add(box);
  });

  // ---------------------------------------------------------------- wires
  const wires = {};
  function tube(curve, segments = 1) {
    return new THREE.TubeGeometry(curve, segments, 0.04, 6, false);
  }
  for (const [name, { points, dashed }] of Object.entries(WIRES)) {
    const mat = new THREE.MeshBasicMaterial({ color: COLOR.wire });
    const [a, b] = points;
    if (dashed) {
      const len = a.distanceTo(b);
      for (let d = 0; d < len; d += 0.42) {
        const p = a.clone().lerp(b, d / len);
        const q = a.clone().lerp(b, Math.min(d + 0.24, len) / len);
        scene.add(new THREE.Mesh(tube(new THREE.LineCurve3(p, q)), mat));
      }
    } else {
      scene.add(new THREE.Mesh(tube(new THREE.LineCurve3(a, b)), mat));
    }
    wires[name] = mat;
  }
  wires.alert = new THREE.MeshBasicMaterial({ color: COLOR.wire });
  scene.add(new THREE.Mesh(tube(ALERT_ARC, 48), wires.alert));

  // ---------------------------------------------------------------- state colours
  let hovered = null;
  function paint(key) {
    const p = parts[key];
    const node = key.split(".")[0];
    const tone = COLOR[p.state];
    const fill = tone ? tone.fill : COLOR.model;
    const edge = tone ? tone.edge : p.state === "active" || hovered === node ? COLOR.ink : COLOR.edge;
    p.mats.forEach((m) => fadeTo(m, fill));
    p.lines.forEach((m) => fadeTo(m, edge));
  }
  // state: "idle" | "active" | "CRITICAL" | "ERROR" | "WARNING" | "INFO"
  function setState(key, state) {
    const p = parts[key];
    p.state = state;
    paint(key);
    // A node-level state overrides its sub-parts; repaint them so they agree.
    if (!key.includes(".")) {
      for (const k of Object.keys(parts)) if (k.startsWith(`${key}.`)) { parts[k].state = state; paint(k); }
    }
  }
  const wire = (name, on) => fadeTo(wires[name], on ? COLOR.ink : COLOR.wire);

  // ---------------------------------------------------------------- tweens
  const tweens = new Set();
  function tween(duration, update, delay = 0) {
    return new Promise((resolve) => {
      tweens.add({ start: performance.now() + delay, duration, update, resolve, begun: false });
    });
  }
  function stopTweens() {
    for (const t of tweens) t.resolve();
    tweens.clear();
  }
  function runTweens(now) {
    for (const t of tweens) {
      if (now < t.start) continue;
      const p = Math.min(1, (now - t.start) / t.duration);
      t.update(p, !t.begun);
      t.begun = true;
      if (p >= 1) {
        tweens.delete(t);
        t.resolve();
      }
    }
    return tweens.size > 0;
  }

  // ---------------------------------------------------------------- packets (one cube per log line, up to 14)
  const cube = new THREE.BoxGeometry(0.2, 0.2, 0.2);
  const ball = new THREE.SphereGeometry(0.17, 20, 12);
  let packets = [];
  const temporary = new Set();

  function spawn(geometry, hex) {
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: hex, roughness: 0.5 }));
    mesh.castShadow = true;
    mesh.visible = false;
    scene.add(mesh);
    temporary.add(mesh);
    return mesh;
  }
  function remove(mesh) {
    scene.remove(mesh);
    mesh.material.dispose();
    temporary.delete(mesh);
  }
  function clearPackets() {
    for (const m of [...temporary]) remove(m);
    packets = [];
  }

  /** Fly `mesh` from a to b on an arc of the given height. */
  function hop(mesh, a, b, height, duration, delay = 0, { shrink = false } = {}) {
    const from = a.clone();
    return tween(duration, (p) => {
      const t = ease(p);
      mesh.visible = true;
      mesh.position.lerpVectors(from, b, t);
      mesh.position.y += 4 * t * (1 - t) * height;
      mesh.rotation.set(t * Math.PI, t * Math.PI * 0.5, 0);
      if (shrink) mesh.scale.setScalar(1 - Math.max(0, (p - 0.75) * 4));
    }, delay);
  }
  function along(mesh, curve, duration, delay = 0) {
    return tween(duration, (p) => {
      mesh.visible = true;
      curve.getPoint(ease(p), mesh.position);
    }, delay);
  }
  const line = (points) => new THREE.LineCurve3(points[0], points[1]);

  function bucketSpot(i) {
    const angle = i * 2.4;
    const r = 0.18 + (i % 3) * 0.17;
    return v(POS.s3.x + Math.cos(angle) * r, 0.14 + Math.floor(i / 5) * 0.22, POS.s3.z + Math.sin(angle) * r);
  }
  function traySpot(i, n) {
    const cols = Math.min(5, n);
    const rowCount = Math.ceil(n / cols);
    return v(POS.lambda.x + (i % cols - (cols - 1) / 2) * 0.27, 1.62, POS.lambda.z + (Math.floor(i / cols) - (rowCount - 1) / 2) * 0.27);
  }

  // ---------------------------------------------------------------- the steps
  async function upload(count) {
    clearPackets();
    for (const id of Object.keys(nodes)) setState(id, "idle");
    Object.keys(wires).forEach((w) => wire(w, false));
    setState("source", "active");
    wire("upload", true);
    const n = Math.max(3, Math.min(14, count || 6));
    packets = Array.from({ length: n }, () => ({ mesh: spawn(cube, COLOR.ink), kind: "ok" }));
    await Promise.all(packets.map((pk, i) => hop(pk.mesh, v(POS.source.x, 1.25, POS.source.z), bucketSpot(i), 1.8, 620, i * 70)));
    setState("source", "idle");
    setState("s3", "active");
  }

  async function trigger() {
    wire("trigger", true);
    const event = spawn(ball, COLOR.ink);
    event.scale.setScalar(0.6);
    await along(event, line(WIRES.trigger.points), 420);
    remove(event);
    setState("lambda", "active");
    ring.visible = true;
    await Promise.all(packets.map((pk, i) => hop(pk.mesh, pk.mesh.position, traySpot(i, packets.length), 1.3, 520, i * 45)));
    setState("s3", "idle");
  }

  async function validate(run) {
    const n = packets.length;
    const share = (k) => (k ? Math.min(n - 1, Math.max(1, Math.round((k / (run.total_lines || n)) * n))) : 0);
    const order = packets.map((_, i) => i).sort(() => Math.random() - 0.5);
    const bad = share(run.rejected);
    const masked = share(run.pii_redacted);
    order.slice(0, bad).forEach((i) => { packets[i].kind = "bad"; });
    order.slice(bad, bad + masked).forEach((i) => { packets[i].kind = "masked"; });

    await Promise.all(packets.map((pk, i) => {
      if (pk.kind === "masked") {
        fadeTo(pk.mesh.material, COLOR.INFO.edge);
        return tween(500, (p) => { pk.mesh.rotation.y = p * Math.PI * 2; }, i * 30);
      }
      if (pk.kind !== "bad") return sleep(400);
      fadeTo(pk.mesh.material, COLOR.ERROR.edge);
      const from = pk.mesh.position.clone();
      const to = v(POS.lambda.x + 1.15 + Math.random() * 0.5, 0.1, POS.lambda.z + 0.6 + Math.random() * 0.6);
      return tween(800, (p) => {
        pk.mesh.position.set(from.x + (to.x - from.x) * p, from.y + (to.y - from.y) * p * p, from.z + (to.z - from.z) * p);
        pk.mesh.rotation.z = p * 3;
      }, 250 + i * 40);
    }));
  }

  async function store() {
    wire("store", true);
    setState("dynamo.events", "active");
    const keep = packets.filter((pk) => pk.kind !== "bad");
    const into = v(POS.dynamo.x - 0.75, DISC.events, POS.dynamo.z - 0.6);
    await Promise.all(keep.map((pk, i) => hop(pk.mesh, pk.mesh.position, into, 1.6, 560, i * 50, { shrink: true })));
    keep.forEach((pk) => { pk.mesh.visible = false; });
  }

  async function detect(run) {
    const found = (run.detections || []).slice(0, 3);
    ring.visible = false;
    setState("lambda", "idle");
    setState("dynamo.events", "idle");
    await Promise.all(found.map((d, i) => {
      const pulse = spawn(ball, COLOR[d.severity]?.edge ?? COLOR.ink);
      return hop(pulse, v(POS.lambda.x, 1.7, POS.lambda.z), v(POS.dynamo.x - 0.8, DISC.incidents, POS.dynamo.z - 0.5), 1.8, 700, i * 160, { shrink: true })
        .then(() => remove(pulse));
    }));
    const worst = ["CRITICAL", "ERROR", "WARNING", "INFO"].find((s) => found.some((d) => d.severity === s));
    if (worst) setState("dynamo.incidents", worst);
    setState("dynamo.runs", "active");
    await sleep(found.length ? 350 : 650);
    setState("dynamo.runs", "idle");
  }

  async function alert(run) {
    if (!run.alerts?.length) return sleep(500);
    wire("alert", true);
    const pulse = spawn(ball, COLOR.CRITICAL.edge);
    await along(pulse, ALERT_ARC, 950);
    remove(pulse);
    setState("sns", "CRITICAL");
    beacon.material.emissiveIntensity = 0.35;
    const waves = [0, 1, 2].map((i) => {
      const wave = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.56, 48), new THREE.MeshBasicMaterial({ color: COLOR.CRITICAL.edge, transparent: true, side: THREE.DoubleSide }));
      wave.rotation.x = -Math.PI / 2;
      wave.position.set(POS.sns.x, 1.95, POS.sns.z);
      wave.visible = false;
      scene.add(wave);
      temporary.add(wave);
      return tween(1000, (p) => {
        wave.visible = true;
        wave.scale.setScalar(1 + p * 3.2);
        wave.material.opacity = 0.85 * (1 - p);
      }, i * 260).then(() => { wave.geometry.dispose(); remove(wave); });
    });
    wire("notify", true);
    const page = spawn(ball, COLOR.CRITICAL.edge);
    await along(page, line(WIRES.notify.points), 650, 250);
    remove(page);
    setState("oncall", "CRITICAL");
    const phone = nodes.oncall.group;
    await Promise.all([...waves, tween(700, (p) => { phone.rotation.z = Math.sin(p * Math.PI * 10) * 0.1 * (1 - p); })]);
  }

  async function failed() {
    ring.visible = false;
    setState("lambda", "CRITICAL");
    await Promise.all(packets.map((pk, i) => {
      fadeTo(pk.mesh.material, COLOR.CRITICAL.edge);
      return tween(500, (p) => { pk.mesh.position.y = 1.62 - p * 1.5; }, i * 30);
    }));
    setState("dynamo.runs", "CRITICAL");
  }

  const STEPS = { upload: (run) => upload(run.total_lines), trigger, validate, store, detect, alert, failed };

  // ---------------------------------------------------------------- playback
  let token = 0;
  let calm;
  function interrupt() {
    token += 1;
    clearTimeout(calm);
    stopTweens();
    ring.visible = false;
    beacon.material.emissiveIntensity = 0;
    nodes.oncall.group.rotation.z = 0;
  }
  function restAll() {
    for (const id of Object.keys(nodes)) setState(id, "idle");
    Object.keys(wires).forEach((w) => wire(w, false));
    beacon.material.emissiveIntensity = 0;
  }

  /** Play `keys` (from storySteps) for this run, starting at `from`. Resolves true if it finished. */
  async function play(run, keys, { from = 0, onStep } = {}) {
    interrupt();
    const mine = token;
    for (let i = from; i < keys.length; i++) {
      onStep?.(i);
      await STEPS[keys[i]](run);
      if (mine !== token) return false;
    }
    onStep?.(keys.length);
    // Leave the outcome on show for a while, then let the model rest.
    calm = setTimeout(() => { if (mine === token) { clearPackets(); restAll(); } }, 7000);
    return true;
  }

  /** A file has been uploaded but the processor has not reported yet. */
  async function pending(lineCount) {
    interrupt();
    const mine = token;
    await upload(lineCount);
    return mine === token;
  }

  /** Show the model at rest, with no animation. */
  function settle() {
    interrupt();
    clearPackets();
    restAll();
  }

  // ---------------------------------------------------------------- picking
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  function nodeAt(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    return raycaster.intersectObjects(pickable, false)[0]?.object.userData.node ?? null;
  }
  let downAt = null;
  const onMove = (e) => {
    if (e.buttons) return;
    const id = nodeAt(e);
    if (id === hovered) return;
    const was = hovered;
    hovered = id;
    for (const key of Object.keys(parts)) if ([was, id].includes(key.split(".")[0])) paint(key);
    renderer.domElement.style.cursor = id ? "pointer" : "grab";
  };
  const onDown = (e) => { downAt = [e.clientX, e.clientY]; };
  const onUp = (e) => {
    if (downAt && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) < 5) onPick?.(nodeAt(e));
    downAt = null;
  };
  const onLeave = () => onMove({ buttons: 0, clientX: -1e4, clientY: -1e4 });
  renderer.domElement.addEventListener("pointermove", onMove);
  renderer.domElement.addEventListener("pointerdown", onDown);
  renderer.domElement.addEventListener("pointerup", onUp);
  renderer.domElement.addEventListener("pointerleave", onLeave);

  // ---------------------------------------------------------------- sizing and the frame loop
  const corners = [];
  for (const x of [BOUNDS.min.x, BOUNDS.max.x]) for (const y of [BOUNDS.min.y, BOUNDS.max.y]) for (const z of [BOUNDS.min.z, BOUNDS.max.z]) corners.push(v(x, y, z));
  let dirty = true;
  function fit() {
    const w = host.clientWidth;
    const h = host.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h);
    labels.setSize(w, h);
    camera.updateMatrixWorld();
    let half = 0;
    let halfY = 0;
    for (const c of corners) {
      const p = c.clone().sub(target).applyMatrix4(new THREE.Matrix4().extractRotation(camera.matrixWorldInverse));
      half = Math.max(half, Math.abs(p.x));
      halfY = Math.max(halfY, Math.abs(p.y));
    }
    const aspect = w / h;
    const top = Math.max(halfY, half / aspect) * 1.02;
    Object.assign(camera, { left: -top * aspect, right: top * aspect, top, bottom: -top });
    camera.updateProjectionMatrix();
    dirty = true;
  }
  const resize = new ResizeObserver(fit);
  resize.observe(host);
  fit();

  let visible = true;
  const seen = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; dirty = true; });
  seen.observe(host);
  controls.addEventListener("change", () => { dirty = true; });

  let frame;
  let last = performance.now();
  function loop(now) {
    frame = requestAnimationFrame(loop);
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    if (!visible || document.hidden) return;
    let busy = runTweens(now);
    const k = 1 - Math.exp(-dt * 9);
    for (const f of fades) {
      f.color.lerp(f.target, k);
      const { r, g, b } = f.target;
      if (Math.abs(f.color.r - r) + Math.abs(f.color.g - g) + Math.abs(f.color.b - b) < 0.004) {
        f.color.copy(f.target);
        fades.delete(f);
      }
      busy = true;
    }
    if (ring.visible) {
      ring.rotation.z -= dt * 3;
      busy = true;
    }
    if (controls.update()) busy = true;
    if (busy || dirty) {
      renderer.render(scene, camera);
      labels.render(scene, camera);
      dirty = false;
    }
  }
  frame = requestAnimationFrame(loop);

  return {
    anchors: Object.fromEntries(Object.entries(nodes).map(([id, n]) => [id, n.anchor])),
    play,
    pending,
    settle,
    resetView() {
      controls.reset();
      dirty = true;
    },
    dispose() {
      interrupt();
      cancelAnimationFrame(frame);
      resize.disconnect();
      seen.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener("pointermove", onMove);
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("pointerleave", onLeave);
      scene.traverse((o) => {
        o.geometry?.dispose();
        o.material?.dispose();
      });
      renderer.dispose();
      renderer.domElement.remove();
      labels.domElement.remove();
    },
  };
}

/** True when this browser can draw the model; otherwise LiveModel falls back to the flat diagram. */
export function canRender() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}
