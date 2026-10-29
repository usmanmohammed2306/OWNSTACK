import * as THREE from 'three/webgpu';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { variationFrame, type Scenario } from './variationModel';
import { springStep } from './spatialMotion';

export type SpatialView = { scenario: Scenario; stage: number; motion: boolean; visible: boolean };
export type WorkspaceRenderer = { update: (view: SpatialView) => void; rotate: (direction: number) => void; dispose: () => void };

/** Optional explanatory scene. No API, account, request or permission input. */
export async function createWorkspaceRenderer(container: HTMLElement, initial: SpatialView, onFailure: () => void): Promise<WorkspaceRenderer> {
  let disposed = false, failed = false, frame = 0, previous = 0;
  let view = initial;
  const geometries: THREE.BufferGeometry[] = [], materials: THREE.Material[] = [], textures: THREE.Texture[] = [];
  const renderer = new THREE.WebGPURenderer({ antialias: true, alpha: true });
  const scene = new THREE.Scene(), group = new THREE.Group();
  const camera = new THREE.PerspectiveCamera(34, 1, .1, 40);
  camera.position.set(4.7, 4.8, 6.8);
  camera.lookAt(0, .3, 0);
  let observer: ResizeObserver | undefined;
  let yaw = -.12, yawVelocity = 0, targetYaw = -.12, lift = .75, liftVelocity = 0;
  let dragging = false, lastX = 0;
  const canvas = renderer.domElement;
  function dispose() {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    observer?.disconnect();
    canvas.removeEventListener('pointerdown', down);
    canvas.removeEventListener('pointermove', move);
    canvas.removeEventListener('pointerup', up);
    canvas.removeEventListener('pointercancel', up);
    canvas.removeEventListener('lostpointercapture', up);
    canvas.removeEventListener('webglcontextlost', lost);
    canvas.remove();
    scene.clear();
    geometries.forEach(item => item.dispose());
    materials.forEach(item => item.dispose());
    textures.forEach(item => item.dispose());
    key.shadow.dispose();
    void renderer.dispose().catch(() => {});
  }
  function fail() { if (!disposed && !failed) { failed = true; dispose(); onFailure(); } }
  function lost(event: Event) { event.preventDefault(); fail(); }
  function requestFrame() { if (!disposed && !frame) frame = requestAnimationFrame(draw); }
  function down(event: PointerEvent) {
    if (event.pointerType !== 'mouse' || event.button !== 0) return;
    dragging = true; lastX = event.clientX; canvas.setPointerCapture(event.pointerId);
    canvas.style.cursor = 'grabbing';
  }
  function move(event: PointerEvent) {
    if (!dragging || event.pointerType !== 'mouse') return;
    targetYaw = THREE.MathUtils.clamp(targetYaw + (event.clientX - lastX) * .004, -.55, .35);
    lastX = event.clientX; requestFrame();
  }
  function up() { dragging = false; canvas.style.cursor = 'grab'; }
  function box(width: number, height: number, depth: number, color: number, x: number, y: number, z: number, parent = group) {
    const geometry = new RoundedBoxGeometry(width, height, depth, 3, .08);
    const material = new THREE.MeshStandardNodeMaterial({ color, roughness: .48, metalness: .12 });
    geometries.push(geometry); materials.push(material);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.castShadow = true; mesh.receiveShadow = true;
    mesh.position.set(x, y, z); parent.add(mesh);
    return mesh;
  }
  function text(value: string, x: number, y: number, z: number, width: number, parent = group) {
    const surface = document.createElement('canvas'); surface.width = 512; surface.height = 128;
    const context = surface.getContext('2d');
    if (!context) return;
    context.font = '500 46px system-ui'; context.textAlign = 'center'; context.textBaseline = 'middle';
    context.fillStyle = '#554a3d'; context.fillText(value, 256, 64);
    const texture = new THREE.CanvasTexture(surface); texture.colorSpace = THREE.SRGBColorSpace; textures.push(texture);
    const material = new THREE.MeshBasicNodeMaterial({ map: texture, transparent: true, depthWrite: false });
    const geometry = new THREE.PlaneGeometry(width, width / 4); materials.push(material); geometries.push(geometry);
    const label = new THREE.Mesh(geometry, material); label.position.set(x, y, z); parent.add(label);
  }
  const atlas = new THREE.Group(); atlas.position.set(-1.5, .75, .15); group.add(atlas);
  const nova = new THREE.Group(); nova.position.set(1.5, .75, .15); group.add(nova);
  box(5.7, .22, 3.6, 0xd6ccbd, 0, -.32, 0);
  box(5.45, .14, 3.35, 0xeee7dd, 0, -.12, 0);
  box(2.3, .35, 1, 0xd9c7b2, 0, .22, -1.05);
  text('One shared app', 0, .26, -.52, 2);
  const atlasFace = box(1.9, 1.35, .2, 0xf7efe3, 0, .25, 0, atlas);
  box(1.9, 1.35, .2, 0xe6e2d9, 0, .25, 0, nova);
  text('Atlas', 0, .50, .12, 1.25, atlas); text('Nova', 0, .50, .12, 1.25, nova);
  box(1.25, .07, .025, 0xd6c4ad, 0, .15, .12, atlas);
  box(.85, .05, .025, 0xe1d3bf, -.2, -.02, .12, atlas);
  box(1.25, .07, .025, 0xd0c8bb, 0, .15, .12, nova);
  box(.85, .05, .025, 0xd8d0c4, -.2, -.02, .12, nova);
  const gate = box(.52, .55, .32, 0xc88c62, 0, .35, .9);
  const route = box(2.55, .035, .045, 0xc7b79e, -1.02, -.015, .34); route.rotation.y = -.45;
  const code = box(1.45, .2, .65, 0xc8ad89, 0, .12, 1.15); code.visible = false;
  scene.add(group, new THREE.HemisphereLight(0xfffbf0, 0xa19480, 1.65));
  const key = new THREE.DirectionalLight(0xfff2df, 2.1); key.position.set(-3, 7, 5); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024); key.shadow.camera.left = -5; key.shadow.camera.right = 5;
  key.shadow.camera.top = 5; key.shadow.camera.bottom = -5; key.shadow.normalBias = .025; scene.add(key);
  const rim = new THREE.DirectionalLight(0xe8efff, 1.1); rim.position.set(5, 3, -4); scene.add(rim);
  function draw(now: number) {
    frame = 0; if (disposed) return;
    const delta = previous ? Math.min((now - previous) / 1000, 1 / 30) : 1 / 60; previous = now;
    const model = variationFrame(view.scenario, view.stage);
    const targetLift = model.atlas === 'temporary' ? 1 : model.atlas === 'preview' ? .86 : .75;
    const moving = view.motion && view.visible;
    const turn = moving ? springStep(yaw, yawVelocity, targetYaw, delta) : { position: targetYaw, velocity: 0, settled: true };
    const height = moving ? springStep(lift, liftVelocity, targetLift, delta) : { position: targetLift, velocity: 0, settled: true };
    yaw = turn.position; yawVelocity = turn.velocity; lift = height.position; liftVelocity = height.velocity;
    group.rotation.y = yaw; atlas.position.y = lift;
    atlasFace.material.color.setHex(model.atlas === 'temporary' ? 0xe5ebd4 : model.atlas === 'preview' ? 0xf2dfc4 : 0xf7efe3);
    route.material.color.setHex(model.route === 'atlas' ? 0x87965b : model.route === 'closed' ? 0xd6cabe : 0xc7b79e);
    route.visible = model.route !== 'engineering'; code.visible = model.route === 'engineering';
    gate.rotation.y = model.route === 'atlas' ? .8 : 0;
    try { renderer.render(scene, camera); } catch { fail(); return; }
    if (moving && (!turn.settled || !height.settled)) requestFrame();
  }
  function resize() {
    if (disposed) return;
    const width = Math.max(container.clientWidth, 1), height = Math.max(container.clientHeight, 1);
    camera.aspect = width / height;
    camera.position.set(4.7, 4.8, 6.8).multiplyScalar(camera.aspect < 1.1 ? 1.4 : 1);
    camera.lookAt(0, .3, 0); camera.updateProjectionMatrix();
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5)); renderer.setSize(width, height, false); requestFrame();
  }
  try {
    await renderer.init();
    canvas.style.cssText = 'display:block;width:100%;height:100%;touch-action:pan-y pinch-zoom;cursor:grab';
    canvas.setAttribute('aria-hidden', 'true');
    canvas.dataset.renderer = 'isWebGPUBackend' in renderer.backend ? 'webgpu' : 'webgl2';
    renderer.setClearColor(0xf5f0e7, 0); renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = .9;
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.onDeviceLost = fail;
    canvas.addEventListener('pointerdown', down); canvas.addEventListener('pointermove', move);
    canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', up); canvas.addEventListener('lostpointercapture', up);
    canvas.addEventListener('webglcontextlost', lost);
    container.appendChild(canvas); observer = new ResizeObserver(resize); observer.observe(container); resize();
    return { update(next) { view = next; previous = 0; requestFrame(); },
      rotate(direction) { targetYaw = THREE.MathUtils.clamp(targetYaw + direction * .15, -.55, .35); requestFrame(); }, dispose };
  } catch (error) { dispose(); throw error; }
}
