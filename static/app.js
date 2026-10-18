/* UNPAM Smart Campus Navigation - front end
 * Three.js 3D viewer + Vanilla Framework UI (light / dark theme).
 * Routing is done by the Flask API (Dijkstra). Room boxes are laid out like the PDF plans. */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

const SELECTABLE = new Set(['classroom', 'lab', 'office', 'toilet', 'prayer', 'service', 'lobby', 'gate']);
const KIND_HEIGHT = { classroom: 3, lab: 3, office: 3, toilet: 3, prayer: 3, service: 3, void: 1.2,
  lobby: 0.8, gate: 7, lift: 4.4, stairs: 3.6, escalator: 3.2 };
const MODE_COLOR = { walk: 'walk', outdoor: 'walk', lift: 0xf99b11, stairs: 0xf99b11, escalator: 0xf99b11 };

/* ------------------------------------------------------------------ themes */
const THEMES = {
  light: { ground: 0xdfe6ec, gridA: 0x9fb3c8, gridB: 0xc3cfdb, gridOpacity: 0.55, outline: 0x1d2733,
    hemiSky: 0xffffff, hemiGround: 0x9aa7b8, hemi: 1.05, sun: 1.1, tileMix: 0xffffff, tileAmt: 0.8,
    tileOpacity: 0.62, roomDim: 1, walk: 0x0066cc, walker: 0xffffff, walkerRing: 0x0066cc, outdoor: 0xb9c3cf },
  dark: { ground: 0x131920, gridA: 0x2d3a49, gridB: 0x212b36, gridOpacity: 0.9, outline: 0x04070a,
    hemiSky: 0xbfd4ff, hemiGround: 0x141b24, hemi: 0.95, sun: 0.85, tileMix: 0x0b0f14, tileAmt: 0.78,
    tileOpacity: 0.85, roomDim: 0.8, walk: 0x4aa3ff, walker: 0xffffff, walkerRing: 0x4aa3ff, outdoor: 0x3a4655 },
};
const THEME_KEY = 'unpam-theme';
let themeName = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
const T = () => THEMES[themeName];

/* ------------------------------------------------------------------ state */
const state = {
  nodes: [], byId: new Map(), meta: null, kinds: {},
  spacing: 9, compact: true,
  focusB: null, focusF: null,
  routeOnly: false, labels: true, follow: true,
  start: null, end: null, route: null, pathSet: null, routeFloors: new Set(),
  hover: -1, pick: null,
};

/* ------------------------------------------------------------------ three.js setup */
const viewport = $('#viewport');
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
viewport.appendChild(renderer.domElement);

const labelRenderer = new CSS2DRenderer();
labelRenderer.domElement.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden;';
viewport.appendChild(labelRenderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(42, 1, 1, 4000);
camera.position.set(-200, 200, 420);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI / 2 - 0.02;
controls.minDistance = 8;
controls.maxDistance = 1400;
controls.autoRotateSpeed = 0.6;

const hemi = new THREE.HemisphereLight(0xffffff, 0x9aa7b8, 1.05);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xffffff, 1.1);
sun.position.set(-120, 260, 160);
scene.add(sun);

const world = new THREE.Group();
scene.add(world);
const floorGroup = new THREE.Group();
const roomGroup = new THREE.Group();
const pathGroup = new THREE.Group();
const pinGroup = new THREE.Group();
const labelGroup = new THREE.Group();
world.add(floorGroup, roomGroup, pathGroup, pinGroup, labelGroup);

const floorObjs = new Map();              // "A6" -> {group, tileMat, base, label, b, f, level, plan}
const buildingLabels = [];
const outdoorMats = [];
let ground = null, gridObj = null;
let fillMesh = null, outlineMesh = null, drawNodes = [];
let walker = null, routeCurve = null, routeLength = 0;

const tmpM = new THREE.Matrix4();
const tmpC = new THREE.Color();
const tmpV = new THREE.Vector3(), tmpS = new THREE.Vector3(), tmpQ = new THREE.Quaternion();
const ZERO = new THREE.Matrix4().makeScale(0, 0, 0);

function resize() {
  const w = viewport.clientWidth, h = viewport.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h);
  labelRenderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(viewport);

/* ------------------------------------------------------------------ helpers */
const yOfLevel = (level, floor) => (state.compact ? level : floor - 1) * state.spacing;
const nodeY = (n) => yOfLevel(n.l, n.f);
const floorKey = (b, f) => `${b}${f}`;
const kindColor = (k) => (state.kinds[k] ? state.kinds[k].color : '#999999');
const heightOf = (n) => KIND_HEIGHT[n.k] ?? 3;
const ptVec = (c, lift = 0.9) => new THREE.Vector3(c[0], yOfLevel(c[2], c[3]) + lift, c[1]);   // [x, z, level, floor, b]

function makeLabel(text, cls, pos) {
  const el = document.createElement('div');
  el.className = cls;
  el.textContent = text;
  const o = new CSS2DObject(el);
  o.position.copy(pos);
  return o;
}

function floorLevelState(b, f) {
  let lvl = 'full';
  if (state.focusB && b !== state.focusB) lvl = 'ghost';
  else if (state.focusB && state.focusF != null && f !== state.focusF) lvl = 'hidden';
  if (state.route && state.routeOnly && lvl !== 'hidden' && !state.routeFloors.has(floorKey(b, f))) lvl = 'ghost';
  return lvl;
}
const nodeVisible = (n) => n.b === 'Campus' || floorLevelState(n.b, n.f) === 'full';

/* ------------------------------------------------------------------ static scene */
function buildScene() {
  ground = new THREE.Mesh(new THREE.PlaneGeometry(1600, 1600), new THREE.MeshStandardMaterial({ color: T().ground, roughness: 1 }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(0, -0.6, 120);
  scene.add(ground);
  makeGrid();

  // outdoor walkway strips
  for (const [x1, z1, x2, z2] of state.meta.outdoor) {
    const len = Math.hypot(x2 - x1, z2 - z1);
    const mat = new THREE.MeshStandardMaterial({ color: T().outdoor, roughness: 1 });
    outdoorMats.push(mat);
    const m = new THREE.Mesh(new THREE.BoxGeometry(len + 3, 0.2, 3.4), mat);
    m.position.set((x1 + x2) / 2, -0.35, (z1 + z2) / 2);
    m.rotation.y = -Math.atan2(z2 - z1, x2 - x1);
    scene.add(m);
  }

  // buildings: floor tiles (the corridors) per floor + floor labels
  const tileGeo = new THREE.BoxGeometry(1, 0.3, 1);
  const G = state.meta.grid;
  for (const bd of state.meta.buildings) {
    const base = new THREE.Color(bd.color);
    for (const fl of bd.floors) {
      const g = new THREE.Group();
      const tileMat = new THREE.MeshStandardMaterial({ transparent: true, depthWrite: false, roughness: 1 });
      const tiles = new THREE.InstancedMesh(tileGeo, tileMat, fl.runs.length);
      fl.runs.forEach(([xa, xb, z], i) => {
        tmpM.compose(tmpV.set((xa + xb) / 2, -0.15, z), tmpQ.identity(), tmpS.set(xb - xa + G, 1, G));
        tiles.setMatrixAt(i, tmpM);
      });
      tiles.instanceMatrix.needsUpdate = true;
      tiles.frustumCulled = false;
      g.add(tiles);
      const lbl = makeLabel(`Floor ${fl.floor}${fl.plan ? '' : ' *'}`, 'lbl-floor' + (fl.plan ? '' : ' is-noplan'),
        new THREE.Vector3(fl.x0 - 3, 0.5, (fl.z0 + Math.min(fl.z1, fl.z0 + 60)) / 2));
      g.add(lbl);
      floorGroup.add(g);
      floorObjs.set(floorKey(bd.id, fl.floor), { group: g, tileMat, base, label: lbl, b: bd.id, f: fl.floor, level: fl.level, plan: fl.plan });
    }
    const top = bd.floors[bd.floors.length - 1];
    const bl = makeLabel(bd.name, 'lbl-building', new THREE.Vector3((bd.x0 + bd.x1) / 2, 0, bd.z0 - 4));
    bl.element.style.background = bd.color;
    bl.userData = { b: bd.id, top };
    floorGroup.add(bl);
    buildingLabels.push(bl);
  }

  // rooms: one instanced mesh (+ inverted-hull outline) for speed
  drawNodes = state.nodes.slice();
  const box = new THREE.BoxGeometry(1, 1, 1);
  fillMesh = new THREE.InstancedMesh(box, new THREE.MeshStandardMaterial({ roughness: 0.65, metalness: 0.05 }), drawNodes.length);
  outlineMesh = new THREE.InstancedMesh(box, new THREE.MeshBasicMaterial({ color: T().outline, side: THREE.BackSide }), drawNodes.length);
  fillMesh.frustumCulled = outlineMesh.frustumCulled = false;
  fillMesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(drawNodes.length * 3), 3);
  roomGroup.add(outlineMesh, fillMesh);
}

function makeGrid() {
  if (gridObj) { scene.remove(gridObj); gridObj.geometry.dispose(); gridObj.material.dispose(); }
  gridObj = new THREE.GridHelper(1600, 160, T().gridA, T().gridB);
  gridObj.position.set(0, -0.55, 120);
  gridObj.material.transparent = true;
  gridObj.material.opacity = T().gridOpacity;
  scene.add(gridObj);
}

/* apply the theme to everything that is not plain CSS */
function applySceneTheme() {
  const th = T();
  if (!ground) return;
  ground.material.color.set(th.ground);
  makeGrid();
  hemi.color.set(th.hemiSky); hemi.groundColor.set(th.hemiGround); hemi.intensity = th.hemi;
  sun.intensity = th.sun;
  outlineMesh.material.color.set(th.outline);
  outdoorMats.forEach((m) => m.color.set(th.outdoor));
  for (const fo of floorObjs.values()) fo.tileMat.color.copy(fo.base).lerp(tmpC.set(th.tileMix), th.tileAmt);
  requestRefresh();
}

/* ------------------------------------------------------------------ refresh (layout + visibility + colours) */
let refreshQueued = false;
function requestRefresh() {
  if (refreshQueued) return;
  refreshQueued = true;
  requestAnimationFrame(() => { refreshQueued = false; refresh(); });
}

function nodeColor(n, i) {
  if (n.id === state.start) return '#0e8420';
  if (n.id === state.end) return '#c7162b';
  if (state.pathSet && state.pathSet.has(n.id)) return '#ffc247';
  tmpC.set(kindColor(n.k)).multiplyScalar(T().roomDim);
  if (i === state.hover) tmpC.offsetHSL(0, 0, 0.14);
  return tmpC.getStyle();
}

function refresh() {
  if (!fillMesh) return;
  const th = T();

  for (const fo of floorObjs.values()) {
    const lvl = floorLevelState(fo.b, fo.f);
    fo.group.position.y = yOfLevel(fo.level, fo.f);
    fo.group.visible = lvl !== 'hidden';
    fo.tileMat.color.copy(fo.base).lerp(tmpC.set(th.tileMix), th.tileAmt);
    fo.tileMat.opacity = (lvl === 'full' ? th.tileOpacity : th.tileOpacity * 0.16) * (fo.plan ? 1 : 0.6);
    fo.label.visible = lvl !== 'hidden';
  }
  for (const bl of buildingLabels) {
    const top = bl.userData.top;
    bl.position.y = yOfLevel(top.level, top.floor) + 9;
    bl.visible = !state.focusB || state.focusB === bl.userData.b;
  }

  drawNodes.forEach((n, i) => {
    if (!nodeVisible(n)) {
      fillMesh.setMatrixAt(i, ZERO);
      outlineMesh.setMatrixAt(i, ZERO);
    } else {
      const h = heightOf(n);
      const w = Math.max(n.w * 0.96, 1.2), d = Math.max(n.d * 0.96, 1.2);
      tmpV.set(n.x, nodeY(n) + h / 2, n.z);
      tmpM.compose(tmpV, tmpQ.identity(), tmpS.set(w, h, d));
      fillMesh.setMatrixAt(i, tmpM);
      tmpM.compose(tmpV, tmpQ.identity(), tmpS.set(w + 0.4, h + 0.4, d + 0.4));
      outlineMesh.setMatrixAt(i, tmpM);
    }
    fillMesh.setColorAt(i, tmpC.set(nodeColor(n, i)));
  });
  fillMesh.instanceMatrix.needsUpdate = true;
  outlineMesh.instanceMatrix.needsUpdate = true;
  fillMesh.instanceColor.needsUpdate = true;
  fillMesh.boundingSphere = null;

  rebuildPath();
  rebuildPins();
  rebuildLabels();
  rebuildRail();
}

function setHover(i) {
  if (i === state.hover) return;
  const old = state.hover;
  state.hover = i;
  for (const idx of [old, i]) {
    if (idx < 0) continue;
    fillMesh.setColorAt(idx, tmpC.set(nodeColor(drawNodes[idx], idx)));
  }
  fillMesh.instanceColor.needsUpdate = true;
}

/* ------------------------------------------------------------------ labels, pins, path */
function rebuildLabels() {
  labelGroup.clear();
  if (!(state.labels && state.focusB && state.focusF != null)) return;
  let count = 0;
  for (const n of drawNodes) {
    if (n.b !== state.focusB || n.f !== state.focusF || n.k === 'void') continue;
    if (++count > 220) break;
    const txt = n.label.length > 22 ? n.label.slice(0, 21) + '...' : n.label;
    labelGroup.add(makeLabel(txt, 'lbl-room', new THREE.Vector3(n.x, nodeY(n) + heightOf(n) + 0.8, n.z)));
  }
}

function pinEl(cls, icon, text) {
  const el = document.createElement('div');
  el.className = `pin ${cls}`;
  el.innerHTML = `<div class="pin__bubble"><i class="fa-solid ${icon}"></i>${text ? '<span></span>' : ''}</div><div class="pin__stem"></div>`;
  if (text) $('span', el).textContent = text;
  return el;
}

function rebuildPins() {
  pinGroup.clear();
  const add = (v, cls, icon, text) => {
    const o = new CSS2DObject(pinEl(cls, icon, text));
    o.position.copy(v);
    pinGroup.add(o);
  };
  for (const [id, cls, icon, text] of [[state.start, 'pin--start', 'fa-location-dot', 'Start'],
    [state.end, 'pin--end', 'fa-flag-checkered', 'Destination']]) {
    const n = state.byId.get(id);
    if (n && nodeVisible(n)) add(new THREE.Vector3(n.x, nodeY(n) + heightOf(n) + 1.2, n.z), cls, icon, text);
  }
  if (state.route) {
    const co = state.route.coords;
    for (const st of state.route.steps) {
      if (!['lift', 'stairs', 'escalator'].includes(st.mode)) continue;
      const icon = st.mode === 'lift' ? 'fa-elevator' : 'fa-stairs';
      for (const idx of [st.from, st.to]) {
        const c = co[idx];
        if (floorLevelState(c[4], c[3]) === 'full') add(ptVec(c, 5), 'pin--transit', icon, '');
      }
    }
  }
}

/* drop points that lie on a straight line so the tube is smooth */
function simplify(pts) {
  if (pts.length < 3) return pts;
  const out = [pts[0]];
  for (let i = 1; i < pts.length - 1; i++) {
    const a = out[out.length - 1], b = pts[i], c = pts[i + 1];
    const v1 = b.clone().sub(a), v2 = c.clone().sub(b);
    if (v1.clone().normalize().distanceTo(v2.clone().normalize()) > 1e-3) out.push(b);
  }
  out.push(pts[pts.length - 1]);
  return out;
}

function rebuildPath() {
  pathGroup.clear();
  walker = null; routeCurve = null;
  if (!state.route) return;
  const th = T();
  const pts = state.route.coords.map((c) => ptVec(c, 1.0));
  const all = simplify(pts);
  const full = new THREE.CurvePath();
  for (let i = 1; i < all.length; i++) full.add(new THREE.LineCurve3(all[i - 1], all[i]));
  routeCurve = full;
  routeLength = full.getLength();

  for (const st of state.route.steps) {
    if (st.mode === 'start' || st.mode === 'end') continue;
    const seg = simplify(pts.slice(st.from, st.to + 1));
    if (seg.length < 2) continue;
    const cp = new THREE.CurvePath();
    for (let i = 1; i < seg.length; i++) cp.add(new THREE.LineCurve3(seg[i - 1], seg[i]));
    const geo = new THREE.TubeGeometry(cp, Math.max(4, seg.length * 3), 0.5, 8, false);
    const col = MODE_COLOR[st.mode] === 'walk' ? th.walk : MODE_COLOR[st.mode];
    const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.96, depthTest: false }));
    mesh.renderOrder = 10;
    pathGroup.add(mesh);
  }
  if (state.follow) {
    walker = new THREE.Mesh(new THREE.SphereGeometry(1.2, 20, 16), new THREE.MeshBasicMaterial({ color: th.walker, depthTest: false }));
    walker.renderOrder = 12;
    const ring = new THREE.Mesh(new THREE.TorusGeometry(1.9, 0.28, 8, 24), new THREE.MeshBasicMaterial({ color: th.walkerRing, depthTest: false }));
    ring.rotation.x = Math.PI / 2;
    ring.renderOrder = 11;
    walker.add(ring);
    pathGroup.add(walker);
  }
}

/* ------------------------------------------------------------------ camera moves */
let fly = null;
function flyTo(pos, target, ms = 900, instant = false) {
  if (instant) { camera.position.copy(pos); controls.target.copy(target); fly = null; return; }
  fly = { p0: camera.position.clone(), t0: controls.target.clone(), p1: pos, t1: target, start: performance.now(), ms };
}
/* The camera sits on the +z (south) side, so screen-right = +x and screen-up = -z, like a PDF page. */
function fitBox(box, dir, pad = 1.25, instant = false) {
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.length() / 2, 14);
  const dist = (radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2))) * pad * 0.8;
  flyTo(center.clone().addScaledVector(dir.clone().normalize(), dist), center, 900, instant);
}
const currentDir = () => camera.position.clone().sub(controls.target).normalize();
const DIRS = {
  overview: new THREE.Vector3(-0.55, 0.75, 0.85),
  plan: new THREE.Vector3(-0.05, 1.0, 0.62),      // tilted plan view of one floor
  top: new THREE.Vector3(0, 1, 0.02),             // straight down, PDF orientation
  front: new THREE.Vector3(-0.2, 0.22, 1),
};

function campusBox() {
  const b = new THREE.Box3();
  for (const bd of state.meta.buildings) {
    const top = bd.floors[bd.floors.length - 1];
    b.expandByPoint(new THREE.Vector3(bd.x0, 0, bd.z0));
    b.expandByPoint(new THREE.Vector3(bd.x1, yOfLevel(top.level, top.floor) + 10, bd.z1));
  }
  const gate = state.byId.get('GATE');
  b.expandByPoint(new THREE.Vector3(gate.x - 6, 0, gate.z - 6));
  return b;
}
function focusBox() {
  if (!state.focusB) return campusBox();
  const bd = state.meta.buildings.find((x) => x.id === state.focusB);
  const b = new THREE.Box3();
  const floors = state.focusF != null ? bd.floors.filter((f) => f.floor === state.focusF) : bd.floors;
  for (const f of floors) {
    const y = yOfLevel(f.level, f.floor);
    b.expandByPoint(new THREE.Vector3(f.x0 - 4, y, f.z0 - 4));
    b.expandByPoint(new THREE.Vector3(f.x1 + 4, y + 6, bd.z1 + 2));
  }
  return b;
}
function routeBox(from = 0, to = null) {
  const b = new THREE.Box3();
  state.route.coords.slice(from, (to ?? state.route.coords.length - 1) + 1).forEach((c) => b.expandByPoint(ptVec(c, 1)));
  b.expandByScalar(10);
  return b;
}
function camPreset(name) {
  if (name === 'route') {
    if (!state.route) return toast('Find a route first.');
    return fitBox(routeBox(), currentDir(), 1.1);
  }
  if (name === 'overview') { state.focusB = null; state.focusF = null; refresh(); }
  fitBox(name === 'overview' ? campusBox() : focusBox(), DIRS[name]);
}

/* ------------------------------------------------------------------ picking / tooltip */
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
let mouseDirty = false, mouseXY = { x: 0, y: 0 }, downXY = null;
const tooltip = $('#tooltip');

renderer.domElement.addEventListener('pointermove', (e) => {
  const r = renderer.domElement.getBoundingClientRect();
  mouseXY = { x: e.clientX - r.left, y: e.clientY - r.top };
  mouse.set((mouseXY.x / r.width) * 2 - 1, -(mouseXY.y / r.height) * 2 + 1);
  mouseDirty = true;
});
renderer.domElement.addEventListener('pointerleave', () => { setHover(-1); tooltip.hidden = true; });
renderer.domElement.addEventListener('pointerdown', (e) => { downXY = { x: e.clientX, y: e.clientY }; });
renderer.domElement.addEventListener('pointerup', (e) => {
  if (!downXY || Math.hypot(e.clientX - downXY.x, e.clientY - downXY.y) > 5) return;
  const i = pickAt();
  if (i >= 0) onRoomClicked(drawNodes[i]);
  else hideCard();
});

function pickAt() {
  raycaster.setFromCamera(mouse, camera);
  const hit = raycaster.intersectObject(fillMesh, false)[0];
  return hit ? hit.instanceId : -1;
}

function nodeWhere(n) {
  if (n.b === 'Campus') return 'Outdoors';
  const fl = state.meta.buildings.find((b) => b.id === n.b).floors.find((f) => f.floor === n.f);
  return `Gedung ${n.b} - Floor ${n.f}${n.wing ? ' (rear wing)' : ''}${fl && !fl.plan ? ' (no plan in PDF)' : ''}`;
}
const sizeText = (n) => (n.k === 'gate' || n.k === 'lobby' ? '' : `about ${n.w} x ${n.d} m (estimated)`);

function updateHover() {
  if (!mouseDirty || !fillMesh) return;
  mouseDirty = false;
  const i = pickAt();
  setHover(i);
  if (i < 0) { tooltip.hidden = true; return; }
  const n = drawNodes[i];
  tooltip.innerHTML = '';
  const s = document.createElement('strong'); s.textContent = n.label;
  tooltip.append(s);
  for (const t of [n.desc, `${state.kinds[n.k]?.name ?? n.k} - ${nodeWhere(n)}`, sizeText(n)]) {
    if (!t) continue;
    const sp = document.createElement('span'); sp.textContent = t; tooltip.append(sp);
  }
  tooltip.hidden = false;
  const stage = $('#stage');
  tooltip.style.left = `${Math.max(4, Math.min(mouseXY.x + 14, stage.clientWidth - 270))}px`;
  tooltip.style.top = `${mouseXY.y + 14}px`;
}

/* selection card */
let cardNode = null;
function onRoomClicked(n) {
  if (state.pick && SELECTABLE.has(n.k)) {
    pickers[state.pick].set(n.id, { fly: false });
    endPickMode();
    return;
  }
  cardNode = n;
  $('#sc-title').textContent = n.label;
  $('#sc-sub').textContent = [n.desc, nodeWhere(n), sizeText(n)].filter(Boolean).join(' - ');
  const ok = SELECTABLE.has(n.k);
  $('#sc-start').hidden = !ok;
  $('#sc-end').hidden = !ok;
  $('#select-card').hidden = false;
}
function hideCard() { $('#select-card').hidden = true; cardNode = null; }
$('#sc-close').onclick = hideCard;
$('#sc-start').onclick = () => { pickers.start.set(cardNode.id, { fly: false }); hideCard(); };
$('#sc-end').onclick = () => { pickers.end.set(cardNode.id, { fly: false }); hideCard(); };

function startPickMode(role) {
  state.pick = role;
  document.body.classList.add('pick-mode');
  $('#pick-text').textContent = role === 'start' ? 'Click a room to use as START' : 'Click a room to use as DESTINATION';
  $('#pick-banner').hidden = false;
}
function endPickMode() {
  state.pick = null;
  document.body.classList.remove('pick-mode');
  $('#pick-banner').hidden = true;
}
$('#pick-cancel').onclick = endPickMode;

/* ------------------------------------------------------------------ pickers (search + cascading selects) */
const pickers = {};
const fullName = (n) => (n.desc && !n.desc.startsWith('Room') && !n.desc.startsWith('(') ? `${n.label} - ${n.desc}`
  : n.desc && n.desc.startsWith('Room') ? `${n.label} (${n.desc})` : n.label);

function makePicker(role) {
  const root = $(`.picker[data-role="${role}"]`);
  const input = $('.p-search-box__input', root);
  const results = $('.picker__results', root);
  const selB = $('.sel-building', root), selF = $('.sel-floor', root), selR = $('.sel-room', root);
  const selectable = state.nodes.filter((n) => SELECTABLE.has(n.k));
  let activeIdx = -1, shown = [];

  const buildingOptions = () => {
    selB.innerHTML = '<option value="">Building...</option>';
    for (const [v, t] of [['Campus', 'Campus (Main Gate)'], ...state.meta.buildings.map((b) => [b.id, b.name])]) selB.add(new Option(t, v));
  };
  const floorOptions = (b) => {
    selF.innerHTML = '<option value="">Floor...</option>';
    selR.innerHTML = '<option value="">Room...</option>';
    if (!b) return;
    const fl = [...new Set(selectable.filter((n) => n.b === b).map((n) => n.f))].sort((a, c) => a - c);
    for (const f of fl) selF.add(new Option(b === 'Campus' ? 'Outdoors' : `Floor ${f}`, f));
    if (fl.length === 1) { selF.value = fl[0]; roomOptions(b, fl[0]); }
  };
  const roomOptions = (b, f) => {
    selR.innerHTML = '<option value="">Room...</option>';
    const rooms = selectable.filter((n) => n.b === b && n.f === Number(f)).sort((x, y) => collator.compare(x.label, y.label));
    for (const n of rooms) selR.add(new Option(fullName(n), n.id));
  };

  const api = {
    role,
    set(id, opts = {}) {
      const n = state.byId.get(id);
      if (!n) return;
      state[role] = id;
      selB.value = n.b;
      floorOptions(n.b);
      selF.value = n.f;
      roomOptions(n.b, n.f);
      selR.value = id;
      input.value = fullName(n);
      results.hidden = true;
      clearRoute(false);
      requestRefresh();
      if (opts.fly !== false) {
        if (n.b !== 'Campus') { state.focusB = n.b; state.focusF = n.f; }
        refresh();
        fitBox(focusBox(), DIRS.plan);
      }
    },
    clear() {
      state[role] = null;
      input.value = '';
      selB.value = '';
      floorOptions('');
    },
  };

  const renderResults = () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { results.hidden = true; return; }
    const tokens = q.split(/\s+/);
    shown = [];
    for (const n of selectable) {
      const hay = `${n.label} ${n.desc} ${state.kinds[n.k]?.name ?? ''} gedung ${n.b} floor lantai ${n.f}`.toLowerCase();
      if (!tokens.every((t) => hay.includes(t))) continue;
      const lab = n.label.toLowerCase();
      shown.push({ n, score: lab === q ? 0 : lab.startsWith(q) ? 1 : lab.includes(q) ? 2 : 3 });
    }
    shown.sort((a, b) => a.score - b.score || collator.compare(a.n.label, b.n.label));
    shown = shown.slice(0, 9);
    results.innerHTML = '';
    activeIdx = -1;
    if (!shown.length) {
      const li = document.createElement('li'); li.className = 'p-list__item';
      li.innerHTML = '<button type="button" disabled>No matching place</button>';
      results.append(li);
    }
    shown.forEach(({ n }) => {
      const li = document.createElement('li'); li.className = 'p-list__item';
      const b = document.createElement('button'); b.type = 'button';
      const t = document.createElement('span'); t.textContent = n.label;
      const s = document.createElement('small'); s.textContent = [n.desc, nodeWhere(n)].filter(Boolean).join(' - ');
      b.append(t, s);
      b.onmousedown = (e) => { e.preventDefault(); api.set(n.id); };
      li.append(b);
      results.append(li);
    });
    results.hidden = false;
  };
  const highlight = (d) => {
    const btns = $$('button', results);
    if (!btns.length) return;
    activeIdx = (activeIdx + d + btns.length) % btns.length;
    btns.forEach((b, i) => b.classList.toggle('is-active', i === activeIdx));
    btns[activeIdx].scrollIntoView({ block: 'nearest' });
  };

  input.addEventListener('input', renderResults);
  input.addEventListener('focus', renderResults);
  input.addEventListener('blur', () => setTimeout(() => (results.hidden = true), 120));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); highlight(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); highlight(-1); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      const pick = shown[activeIdx >= 0 ? activeIdx : 0];
      if (pick) api.set(pick.n.id);
    } else if (e.key === 'Escape') results.hidden = true;
  });
  selB.addEventListener('change', () => floorOptions(selB.value));
  selF.addEventListener('change', () => roomOptions(selB.value, selF.value));
  selR.addEventListener('change', () => { if (selR.value) api.set(selR.value); });
  $('.picker__pick', root).addEventListener('click', () => startPickMode(role));

  buildingOptions();
  floorOptions('');
  pickers[role] = api;
  return api;
}

/* ------------------------------------------------------------------ routing */
const msgBox = $('#route-msg');
function toast(text, cls = 'p-notification--caution') {
  msgBox.innerHTML = '';
  const d = document.createElement('div');
  d.className = `${cls} is-dense`;
  d.innerHTML = '<div class="p-notification__content"><p class="p-notification__message"></p></div>';
  $('p', d).textContent = text;
  msgBox.append(d);
}

function clearRoute(full = true) {
  state.route = null;
  state.pathSet = null;
  state.routeFloors = new Set();
  $('#route-result').hidden = true;
  msgBox.innerHTML = '';
  if (full) requestRefresh();
}

async function findRoute() {
  if (!state.start || !state.end) return toast('Choose both a start and a destination first.');
  const btn = $('#btn-go');
  btn.disabled = true;
  try {
    const res = await fetch('/api/find_path', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start: state.start, end: state.end, accessible: $('#chk-access').checked }),
    });
    const data = await res.json();
    if (!data.found) { clearRoute(); return toast(data.message || 'No route found', 'p-notification--negative'); }
    showRoute(data);
  } catch (err) {
    toast('Could not reach the routing API.', 'p-notification--negative');
  } finally {
    btn.disabled = false;
  }
}

const fmtTime = (s) => { const m = Math.floor(s / 60), r = s % 60; return m ? `${m} min ${String(r).padStart(2, '0')} s` : `${r} s`; };

function showRoute(data) {
  state.route = data;
  state.pathSet = new Set(data.path.filter((id) => state.byId.has(id) && ['lift', 'stairs', 'escalator', 'lobby'].includes(state.byId.get(id).k)));
  state.routeFloors = new Set(data.floors.map((x) => floorKey(x.b, x.f)));
  msgBox.innerHTML = '';
  if (data.accessible) {
    const d = document.createElement('div');
    d.className = 'p-notification--positive is-dense';
    d.innerHTML = '<div class="p-notification__content"><p class="p-notification__message"><i class="fa-solid fa-wheelchair"></i> Accessible route: stairs and escalators were excluded.</p></div>';
    msgBox.append(d);
  }
  $('#st-dist').textContent = Math.round(data.distance);
  $('#st-time').textContent = fmtTime(data.time_s);
  $('#st-floors').textContent = data.floors.length || 1;

  const ol = $('#step-list');
  ol.innerHTML = '';
  data.steps.forEach((st) => {
    const li = document.createElement('li');
    const btn = document.createElement('button'); btn.type = 'button';
    const badge = document.createElement('span');
    badge.className = `badge m-${st.mode}`;
    badge.innerHTML = `<i class="fa-solid ${st.icon}"></i>`;
    const t = document.createElement('span'); t.className = 'st-title'; t.textContent = st.title;
    const d = document.createElement('span'); d.className = 'st-detail';
    d.textContent = st.dist ? `${st.detail} - ${st.dist} m` : st.detail;
    btn.append(t, d);
    if (st.pass && st.pass.length) {
      const p = document.createElement('span'); p.className = 'st-pass';
      p.innerHTML = '<i class="fa-solid fa-signs-post"></i>';
      p.append(`Pass ${st.pass.join(', ')}`);
      btn.append(p);
    }
    li.append(badge, btn);
    btn.onclick = () => {
      $$('li', ol).forEach((x) => x.classList.remove('is-active'));
      li.classList.add('is-active');
      fitBox(routeBox(st.from, st.to), currentDir(), 1.0);
    };
    ol.append(li);
  });
  const s = data.stats;
  $('#algo-note').innerHTML = '<i class="fa-solid fa-microchip"></i> ';
  $('#algo-note').append(`Dijkstra settled ${s.nodes_popped} nodes and relaxed ${s.edges_relaxed} edges in ${s.elapsed_ms} ms.`);
  $('#route-result').hidden = false;

  state.focusB = null; state.focusF = null;
  refresh();
  fitBox(routeBox(), DIRS.overview, 1.15);
}

/* ------------------------------------------------------------------ floor rail */
function rebuildRail() {
  const rb = $('#rail-buildings'), rf = $('#rail-floors');
  rb.innerHTML = ''; rf.innerHTML = '';
  const mk = (txt, on, fn, title) => {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = txt;
    if (on) b.classList.add('is-on');
    if (title) b.title = title;
    b.onclick = fn; return b;
  };
  rb.append(mk('All', !state.focusB, () => { state.focusB = null; state.focusF = null; refresh(); fitBox(campusBox(), DIRS.overview); }, 'Show whole campus'));
  for (const bd of state.meta.buildings) {
    rb.append(mk(bd.id, state.focusB === bd.id, () => { state.focusB = bd.id; state.focusF = null; refresh(); fitBox(focusBox(), DIRS.overview); }, bd.name));
  }
  if (!state.focusB) {
    const h = document.createElement('div'); h.className = 'rail-hint'; h.textContent = 'Pick a building to isolate floors';
    rf.append(h); return;
  }
  const bd = state.meta.buildings.find((b) => b.id === state.focusB);
  [...bd.floors].reverse().forEach((f) => {
    const b = mk(String(f.floor), state.focusF === f.floor, () => {
      state.focusF = state.focusF === f.floor ? null : f.floor;
      refresh();
      fitBox(focusBox(), state.focusF != null ? DIRS.plan : DIRS.overview);
    }, f.plan ? `Floor ${f.floor}` : `Floor ${f.floor} (no plan in PDF)`);
    if (!f.plan) b.classList.add('is-noplan');
    if (state.routeFloors.has(floorKey(bd.id, f.floor))) b.classList.add('is-route');
    rf.append(b);
  });
  rf.append(mk('All floors', state.focusF == null, () => { state.focusF = null; refresh(); fitBox(focusBox(), DIRS.overview); }, 'Show every floor'));
}

/* ------------------------------------------------------------------ theme toggle */
function setTheme(name, save = true) {
  themeName = name;
  document.documentElement.setAttribute('data-theme', name);
  const dark = name === 'dark';
  $('#theme-icon').className = `fa-solid ${dark ? 'fa-sun' : 'fa-moon'}`;
  $('#theme-text').textContent = dark ? 'Light' : 'Dark';
  $('#btn-theme').setAttribute('aria-pressed', String(dark));
  if (save) { try { localStorage.setItem(THEME_KEY, name); } catch (e) { /* private mode */ } }
  applySceneTheme();
}

/* ------------------------------------------------------------------ sidebar wiring */
function wireUI() {
  $$('.p-tabs__link').forEach((btn) => btn.addEventListener('click', () => {
    $$('.p-tabs__link').forEach((b) => b.setAttribute('aria-selected', String(b === btn)));
    $$('.tab-panel').forEach((p) => { p.hidden = p.id !== `tab-${btn.dataset.tab}`; });
  }));

  $('#btn-theme').onclick = () => setTheme(themeName === 'dark' ? 'light' : 'dark');
  // follow the operating system until the user picks a theme by hand
  if (window.matchMedia) {
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      let saved = null;
      try { saved = localStorage.getItem(THEME_KEY); } catch (err) { /* ignore */ }
      if (!saved) setTheme(e.matches ? 'dark' : 'light', false);
    });
  }

  $('#btn-go').onclick = findRoute;
  $('#btn-clear').onclick = () => {
    pickers.start.clear(); pickers.end.clear();
    clearRoute(false);
    state.focusB = null; state.focusF = null;
    refresh();
    fitBox(campusBox(), DIRS.overview);
  };
  $('#btn-swap').onclick = () => {
    const s = state.start, e = state.end;
    if (e) pickers.start.set(e, { fly: false }); else pickers.start.clear();
    if (s) pickers.end.set(s, { fly: false }); else pickers.end.clear();
    if (state.start && state.end) findRoute();
  };
  $('#chk-access').onchange = () => { if (state.route && state.start && state.end) findRoute(); };

  $$('[data-cam]').forEach((b) => (b.onclick = () => camPreset(b.dataset.cam)));
  const spacing = $('#rng-spacing');
  spacing.oninput = () => { state.spacing = Number(spacing.value); $('#val-spacing').textContent = spacing.value; requestRefresh(); };
  $('#chk-compact').onchange = (e) => { state.compact = e.target.checked; requestRefresh(); };
  $('#chk-routeonly').onchange = (e) => { state.routeOnly = e.target.checked; requestRefresh(); };
  $('#chk-labels').onchange = (e) => { state.labels = e.target.checked; requestRefresh(); };
  $('#chk-rotate').onchange = (e) => { controls.autoRotate = e.target.checked; };
  $('#chk-follow').onchange = (e) => { state.follow = e.target.checked; requestRefresh(); };

  const ul = $('#legend-list');
  for (const k of ['classroom', 'lab', 'office', 'toilet', 'prayer', 'service', 'lift', 'stairs', 'escalator', 'lobby', 'gate', 'void']) {
    if (!state.kinds[k]) continue;
    const li = document.createElement('li'); li.className = 'p-list__item';
    li.innerHTML = '<span class="swatch"></span><span class="nm"></span>';
    $('.swatch', li).style.background = state.kinds[k].color;
    $('.nm', li).textContent = state.kinds[k].name;
    ul.append(li);
  }

  const openModal = (id) => { $(id).style.display = 'flex'; };
  $$('.p-modal').forEach((m) => m.addEventListener('click', (e) => {
    if (e.target === m || e.target.hasAttribute('data-close')) m.style.display = 'none';
  }));
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { $$('.p-modal').forEach((m) => (m.style.display = 'none')); endPickMode(); }
  });
  $('#btn-about').onclick = () => openModal('#modal-about');
  $('#btn-bench').onclick = async () => {
    openModal('#modal-bench');
    const body = $('#bench-body');
    body.innerHTML = '<p><i class="fa-solid fa-circle-notch fa-spin"></i> Running benchmark...</p>';
    const d = await (await fetch('/api/benchmark?runs=200')).json();
    const c = d.campus;
    body.innerHTML = `
      <p>Campus graph: <strong>V = ${c.V}</strong> nodes (rooms plus corridor grid cells), <strong>E = ${c.E}</strong> edges, stored as an adjacency list (O(V + E) space).
      ${c.queries} random room-to-room queries:</p>
      <table><thead><tr><th>Average</th><th>Fastest</th><th>Slowest</th><th>Avg. nodes settled</th></tr></thead>
      <tbody><tr><td>${c.avg_ms} ms</td><td>${c.min_ms} ms</td><td>${c.max_ms} ms</td><td>${c.avg_nodes_popped}</td></tr></tbody></table>
      <h3 class="p-heading--5">Scaling on random sparse graphs (E is about 2V)</h3>
      <table><thead><tr><th>V</th><th>E</th><th>Avg. time (ms)</th></tr></thead><tbody>
      ${d.scaling.map((r) => `<tr><td>${r.V}</td><td>${r.E}</td><td>${r.avg_ms}</td></tr>`).join('')}</tbody></table>
      <p class="p-text--small u-text--muted">Expected growth: O((V + E) log V). Timings depend on your machine.</p>`;
  };
}

/* ------------------------------------------------------------------ main loop */
const clock = new THREE.Clock();
let walkerT = 0;
function animate() {
  requestAnimationFrame(animate);
  const dt = clock.getDelta();
  if (fly) {
    const k = Math.min(1, (performance.now() - fly.start) / fly.ms);
    const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
    camera.position.lerpVectors(fly.p0, fly.p1, e);
    controls.target.lerpVectors(fly.t0, fly.t1, e);
    if (k >= 1) fly = null;
  }
  updateHover();
  if (walker && routeCurve && routeLength > 0) {
    walkerT = (walkerT + (dt * 45) / routeLength) % 1;
    walker.position.copy(routeCurve.getPointAt(walkerT));
  }
  controls.update();
  renderer.render(scene, camera);
  labelRenderer.render(scene, camera);
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  try {
    const data = await (await fetch('/api/init_data')).json();
    state.nodes = data.nodes;
    state.meta = data.meta;
    state.kinds = data.meta.kinds;
    data.nodes.forEach((n) => state.byId.set(n.id, n));

    $('#graph-size').textContent = `V=${data.stats.V}  E=${data.stats.E}`;
    $('#about-assumed').textContent = data.meta.assumed + ' Floors marked with * have no plan in the PDF.';
    $('#scale-note').textContent = `Layout follows the PDF. Estimated scale: ${data.meta.scale.main} m per PDF point (rear wings ${data.meta.scale.wing}), so a typical classroom is about 7 x 9 m.`;

    buildScene();
    makePicker('start');
    makePicker('end');
    wireUI();
    setTheme(themeName, false);
    resize();
    refresh();
    fitBox(campusBox(), DIRS.overview, 1.15, true);
    animate();
    $('#loading').remove();
  } catch (err) {
    console.error(err);
    const l = $('#loading');
    l.classList.add('is-error');
    l.innerHTML = '<span><i class="fa-solid fa-triangle-exclamation"></i> Could not load the 3D viewer. Check your internet connection (Three.js is loaded from a CDN) and the Flask server.</span>';
  }
}
boot();
