import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { continuousSceneMotion } from './sceneMotion';
import { variationFrame } from './variationModel';

export type CapabilityView = {
  stage: number;
  scenario: 'access' | 'pdf';
  motion: boolean;
  reducedMotion: boolean;
  visible: boolean;
};

export type CapabilityRenderer = {
  update: (options: CapabilityView) => void;
  reset: () => void;
  dispose: () => void;
};

/** A local teaching model. It receives no request, grant, telemetry or credentials. */
export function createCapabilityRenderer(
  container: HTMLElement,
  options: CapabilityView & { onFailure: () => void },
): CapabilityRenderer {
  let view: CapabilityView = { ...options };
  let renderer: THREE.WebGLRenderer | undefined;
  let environment: THREE.WebGLRenderTarget | undefined;
  let observer: ResizeObserver | undefined;
  let disposed = false;
  let frame = 0;
  let previousTime = 0;
  let elapsed = 0;
  let yaw = -0.07;
  let pitch = 0;
  let dragging = false;
  let lastX = 0;
  let lastY = 0;
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  const textures = new Set<THREE.Texture>();
  const shadows = new Set<THREE.LightShadow>();
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-5, 5, 3, -3, 0.1, 60);
  const assembly = new THREE.Group();
  const target = new THREE.Vector3(0, 0.24, 0);
  const noop = () => {};

  function geometry<T extends THREE.BufferGeometry>(value: T): T {
    geometries.add(value);
    return value;
  }

  function material<T extends THREE.Material>(value: T): T {
    materials.add(value);
    return value;
  }

  function mesh(shape: THREE.BufferGeometry, finish: THREE.Material, parent: THREE.Object3D,
    x = 0, y = 0, z = 0) {
    const item = new THREE.Mesh(shape, finish);
    item.position.set(x, y, z);
    parent.add(item);
    return item;
  }

  function rounded(width: number, height: number, depth: number, radius = 0.035) {
    return geometry(new RoundedBoxGeometry(width, height, depth, 2, radius));
  }

  function physicalBox(width: number, height: number, depth: number, finish: THREE.Material,
    parent: THREE.Object3D, x = 0, y = 0, z = 0, radius = 0.035) {
    const item = mesh(rounded(width, height, depth, radius), finish, parent, x, y, z);
    item.castShadow = true;
    item.receiveShadow = true;
    return item;
  }

  function label(text: string, width: number, color = '#d7eafa', size = 40) {
    const surface = document.createElement('canvas');
    surface.width = 1024;
    surface.height = 144;
    const context = surface.getContext('2d');
    if (!context) return undefined;
    context.clearRect(0, 0, surface.width, surface.height);
    context.font = `600 ${size}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.fillStyle = color;
    context.fillText(text, surface.width / 2, surface.height / 2);
    const texture = new THREE.CanvasTexture(surface);
    texture.colorSpace = THREE.SRGBColorSpace;
    textures.add(texture);
    const finish = material(new THREE.MeshBasicMaterial({
      map: texture, transparent: true, depthWrite: false, toneMapped: false,
    }));
    return mesh(geometry(new THREE.PlaneGeometry(width, width * 144 / 1024)), finish, assembly);
  }

  function engraved(text: string, width: number, parent: THREE.Object3D,
    x: number, y: number, z: number, color?: string, size?: number) {
    const item = label(text, width, color, size);
    if (item) {
      parent.add(item);
      item.position.set(x, y, z);
    }
    return item;
  }

  function stopFrame() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    previousTime = 0;
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    stopFrame();
    observer?.disconnect();
    const canvas = renderer?.domElement;
    if (canvas) {
      canvas.removeEventListener('pointerdown', pointerDown);
      canvas.removeEventListener('pointermove', pointerMove);
      canvas.removeEventListener('pointerup', pointerUp);
      canvas.removeEventListener('pointercancel', pointerUp);
      canvas.removeEventListener('lostpointercapture', pointerUp);
      canvas.removeEventListener('webglcontextlost', contextLost);
      canvas.remove();
    }
    scene.clear();
    geometries.forEach(value => value.dispose());
    materials.forEach(value => value.dispose());
    textures.forEach(value => value.dispose());
    shadows.forEach(value => value.dispose());
    environment?.dispose();
    renderer?.dispose();
    renderer?.forceContextLoss();
  }

  function fail() {
    if (disposed) return;
    dispose();
    options.onFailure();
  }

  function contextLost(event: Event) {
    event.preventDefault();
    fail();
  }

  function pointerDown(event: PointerEvent) {
    // The illustration never captures touch scrolling or wheel navigation.
    if (event.pointerType !== 'mouse' || event.button !== 0) return;
    dragging = true;
    lastX = event.clientX;
    lastY = event.clientY;
    renderer?.domElement.setPointerCapture(event.pointerId);
    if (renderer) renderer.domElement.style.cursor = 'grabbing';
  }

  function pointerMove(event: PointerEvent) {
    if (!dragging || event.pointerType !== 'mouse') return;
    // A bounded orbit preserves the front labels and the meaning of each route.
    yaw = THREE.MathUtils.clamp(yaw + (event.clientX - lastX) * 0.003, -0.26, 0.18);
    pitch = THREE.MathUtils.clamp(pitch + (event.clientY - lastY) * 0.002, -0.075, 0.075);
    lastX = event.clientX;
    lastY = event.clientY;
    requestRender();
  }

  function pointerUp() {
    dragging = false;
    if (renderer) renderer.domElement.style.cursor = 'grab';
  }

  let atlasLight: THREE.MeshStandardMaterial;
  let gateLight: THREE.MeshStandardMaterial;
  let engineeringLight: THREE.MeshStandardMaterial;
  let hostLight: THREE.MeshStandardMaterial;
  let atlasRoute: THREE.MeshStandardMaterial;
  let engineeringRoute: THREE.MeshStandardMaterial;
  let leftDoor: THREE.Mesh;
  let rightDoor: THREE.Mesh;
  let contract: THREE.Group;
  let atlasWash: THREE.MeshBasicMaterial;
  let engineeringWash: THREE.MeshBasicMaterial;
  let atlasPoint: THREE.PointLight;
  let engineeringPoint: THREE.PointLight;
  const accessPackets: THREE.Mesh[] = [];
  const engineeringPackets: THREE.Mesh[] = [];
  let accessCurve: THREE.CatmullRomCurve3;
  let engineeringCurve: THREE.CatmullRomCurve3;
  const packetPosition = new THREE.Vector3();

  function draw(now: number) {
    frame = 0;
    if (disposed || !renderer) return;
    const moving = continuousSceneMotion(view);
    const delta = previousTime ? Math.min((now - previousTime) / 1000, 0.04) : 0;
    previousTime = now;
    if (moving) elapsed += delta;
    const interpolation = moving ? 1 - Math.exp(-delta * 9) : 1;
    const display = variationFrame(view.scenario, view.stage);
    const pdf = display.route === 'engineering';
    // Only the illustrative exact-approval step lights the Atlas access path.
    // Neither the PDF branch nor any stage ever changes the Nova module.
    const access = display.route === 'atlas';
    const preview = display.atlas === 'preview';
    const pulse = moving ? Math.sin(elapsed * 1.3) * 0.05 : 0;
    atlasLight.color.setHex(access ? 0x38daf1 : 0x2b5466);
    atlasRoute.color.setHex(access ? 0x25b9db : 0x1c3045);
    engineeringLight.color.setHex(pdf ? 0xe3ad6b : 0x62564a);
    engineeringRoute.color.setHex(pdf ? 0xba8b52 : 0x3e3935);
    atlasLight.emissiveIntensity = access ? 1.85 + pulse : 0.10;
    atlasRoute.emissiveIntensity = access ? 2.1 : 0.015;
    engineeringLight.emissiveIntensity = pdf ? 1.35 + pulse : 0.12;
    engineeringRoute.emissiveIntensity = pdf ? 1.5 : 0.015;
    gateLight.emissiveIntensity = access ? 0.10 : preview ? 1.7 + pulse : 0.64;
    hostLight.emissiveIntensity = 0.92 + pulse;
    atlasWash.opacity = access ? 0.26 : 0.045;
    engineeringWash.opacity = pdf ? 0.20 : 0.02;
    atlasPoint.intensity = access ? 1.25 : 0.10;
    engineeringPoint.intensity = pdf ? 1.1 : 0.10;

    const gateOffset = access ? 0.46 : 0.16;
    leftDoor.position.x = THREE.MathUtils.lerp(leftDoor.position.x, -gateOffset, interpolation);
    rightDoor.position.x = THREE.MathUtils.lerp(rightDoor.position.x, gateOffset, interpolation);
    contract.position.y = THREE.MathUtils.lerp(contract.position.y, display.atlas === 'unchanged' ? 1.27 : 1.16, interpolation);
    contract.visible = !pdf;
    assembly.rotation.y = yaw + (moving ? Math.sin(elapsed * 0.16) * 0.014 : 0);
    assembly.rotation.x = pitch;

    for (let index = 0; index < accessPackets.length; index++) {
      const packet = accessPackets[index];
      packet.visible = access;
      if (access) {
        accessCurve.getPointAt((elapsed * 0.16 + index / accessPackets.length) % 1, packetPosition);
        packet.position.copy(packetPosition);
        packet.position.y += 0.010;
      }
    }
    for (let index = 0; index < engineeringPackets.length; index++) {
      const packet = engineeringPackets[index];
      packet.visible = pdf;
      if (pdf) {
        engineeringCurve.getPointAt((elapsed * 0.14 + index / engineeringPackets.length) % 1, packetPosition);
        packet.position.copy(packetPosition);
        packet.position.y += 0.010;
      }
    }

    try {
      renderer.render(scene, camera);
    } catch {
      fail();
      return;
    }
    if (moving) frame = requestAnimationFrame(draw);
  }

  function requestRender() {
    // Mount, resize and explicit state changes get one static frame even offscreen.
    // Only continuousSceneMotion can schedule a subsequent animation frame.
    if (!disposed && !frame) frame = requestAnimationFrame(draw);
  }

  function resize() {
    if (disposed || !renderer) return;
    const width = Math.max(container.clientWidth, 1);
    const height = Math.max(container.clientHeight, 1);
    const aspect = width / height;
    // The angled board projects wider than its 8.2-unit base. Keep its corners
    // inside narrow canvases as well as the tenant modules, including orbit.
    const halfHeight = Math.max(2.48, 4.7 / aspect);
    camera.left = -halfHeight * aspect;
    camera.right = halfHeight * aspect;
    camera.top = halfHeight;
    camera.bottom = -halfHeight;
    camera.position.set(4.0, 5.1, 9.5).add(target);
    camera.lookAt(target);
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setSize(width, height, false);
    requestRender();
  }

  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
    renderer.setClearColor(0x070f1e, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.04;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    const canvas = renderer.domElement;
    canvas.setAttribute('aria-hidden', 'true');
    canvas.style.cssText = 'display:block;width:100%;height:100%;touch-action:pan-y pinch-zoom;cursor:grab';
    canvas.dataset.renderer = 'webgl';
    container.appendChild(canvas);

    // Reflections and labels are generated locally, without external image assets.
    const room = new RoomEnvironment();
    const pmrem = new THREE.PMREMGenerator(renderer);
    try {
      environment = pmrem.fromScene(room, 0.055);
      scene.environment = environment.texture;
      scene.environmentIntensity = 0.52;
    } finally {
      room.dispose();
      pmrem.dispose();
    }

    scene.add(assembly);
    scene.add(new THREE.HemisphereLight(0xb9d9f5, 0x091020, 1.1));
    const key = new THREE.DirectionalLight(0xe7f2ff, 3.0);
    key.position.set(-4, 8, 5);
    key.castShadow = true;
    shadows.add(key.shadow);
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.left = -5;
    key.shadow.camera.right = 5;
    key.shadow.camera.top = 5;
    key.shadow.camera.bottom = -5;
    key.shadow.bias = -0.0006;
    key.shadow.normalBias = 0.025;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x438cfa, 2.8);
    rim.position.set(4, 3, -4);
    scene.add(rim);
    const warm = new THREE.DirectionalLight(0xf4c68d, 1.25);
    warm.position.set(-4, 2, -3);
    scene.add(warm);

    const navy = material(new THREE.MeshStandardMaterial({ color: 0x111e32, metalness: 0.82, roughness: 0.32 }));
    const alloy = material(new THREE.MeshStandardMaterial({ color: 0x506479, metalness: 0.88, roughness: 0.26 }));
    const edge = material(new THREE.MeshStandardMaterial({ color: 0x24364f, metalness: 0.83, roughness: 0.33 }));
    const recess = material(new THREE.MeshStandardMaterial({ color: 0x070f1c, metalness: 0.40, roughness: 0.50 }));
    const face = material(new THREE.MeshPhysicalMaterial({
      color: 0x09182d, metalness: 0.30, roughness: 0.36, clearcoat: 0.30,
      clearcoatRoughness: 0.24, envMapIntensity: 0.28,
    }));
    const glass = material(new THREE.MeshPhysicalMaterial({
      color: 0x0b2843, metalness: 0.12, roughness: 0.20, transmission: 0.12,
      thickness: 0.12, ior: 1.36, clearcoat: 0.22, clearcoatRoughness: 0.16,
      attenuationColor: 0x1c4e76, attenuationDistance: 1, envMapIntensity: 0.16,
    }));
    const cyanGlass = material(new THREE.MeshPhysicalMaterial({
      color: 0x1b5e7a, metalness: 0.15, roughness: 0.12, transmission: 0.18,
      thickness: 0.09, ior: 1.4, clearcoat: 0.38, envMapIntensity: 0.18,
      emissive: 0x0e3a53, emissiveIntensity: 0.20,
    }));
    const whiteInk = material(new THREE.MeshStandardMaterial({ color: 0x94b3ca, roughness: 0.38, metalness: 0.45 }));
    const quietBlue = material(new THREE.MeshStandardMaterial({
      color: 0x4977b8, emissive: 0x295388, emissiveIntensity: 0.36, metalness: 0.35, roughness: 0.28,
    }));
    function lightMaterial(color: number, intensity: number) {
      return material(new THREE.MeshStandardMaterial({
        color, emissive: color, emissiveIntensity: intensity, metalness: 0.18, roughness: 0.25,
      }));
    }
    hostLight = lightMaterial(0x7fddff, 0.92);
    atlasLight = lightMaterial(0x38daf1, 0.10);
    gateLight = lightMaterial(0xe3ad6b, 0.64);
    engineeringLight = lightMaterial(0xe3ad6b, 0.12);
    atlasRoute = lightMaterial(0x25b9db, 0.015);
    engineeringRoute = lightMaterial(0xba8b52, 0.015);

    const floor = mesh(geometry(new THREE.PlaneGeometry(24, 20)), material(new THREE.ShadowMaterial({ opacity: 0.28 })), scene, 0, -0.90, 0);
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;

    // One continuous foundation represents the single application codebase.
    physicalBox(7.35, 0.31, 4.40, navy, assembly, 0, -0.63, 0, 0.17);
    physicalBox(7.12, 0.06, 4.17, alloy, assembly, 0, -0.445, 0, 0.14);
    physicalBox(6.97, 0.065, 4.02, face, assembly, 0, -0.392, 0, 0.11);
    physicalBox(7.12, 0.08, 4.16, recess, assembly, 0, -0.825, 0, 0.12);
    // Understated cut lines and fasteners make the topology feel fabricated.
    for (const x of [-3.28, 3.28]) for (const z of [-1.77, 1.77]) {
      mesh(geometry(new THREE.CylinderGeometry(0.044, 0.044, 0.025, 12)), alloy, assembly, x, -0.345, z);
      mesh(geometry(new THREE.BoxGeometry(0.050, 0.006, 0.008)), recess, assembly, x, -0.331, z);
    }
    mesh(rounded(6.42, 0.018, 0.012, 0.004), quietBlue, assembly, 0, -0.62, 2.207);
    engraved('OWNSTACK  /  ONE APP, SCOPED VARIATIONS', 4.4, assembly, 0, -0.59, 2.213, '#8fa8c4', 33);
    const cutLine = geometry(new THREE.BoxGeometry(0.012, 0.008, 3.55));
    for (const x of [-0.62, 0.66]) mesh(cutLine, edge, assembly, x, -0.352, 0);

    // The shared application is a single tall translucent software facade.
    const host = new THREE.Group();
    host.position.set(-0.30, -0.34, -1.00);
    assembly.add(host);
    physicalBox(2.72, 0.15, 1.05, navy, host, 0, 0.075, 0, 0.07);
    physicalBox(2.53, 0.035, 0.88, alloy, host, 0, 0.17, 0, 0.03);
    physicalBox(2.42, 2.18, 0.18, navy, host, 0, 1.29, -0.13, 0.095);
    physicalBox(2.29, 2.04, 0.055, face, host, 0, 1.29, -0.025, 0.07);
    for (const x of [-1.23, 1.23]) {
      physicalBox(0.065, 2.20, 0.32, alloy, host, x, 1.29, 0.06, 0.026);
      mesh(rounded(0.016, 1.97, 0.018, 0.006), hostLight, host, x, 1.31, 0.234);
    }
    physicalBox(2.48, 0.067, 0.31, alloy, host, 0, 2.38, 0.06, 0.026);
    physicalBox(2.18, 1.81, 0.055, glass, host, 0, 1.30, 0.215, 0.045);
    engraved('SHARED APP', 2.35, host, 0, 2.11, 0.260, '#dbeeff', 94);
    engraved('ONE CODEBASE', 2.05, host, 0, 0.52, 0.269, '#99b9d2', 62);
    mesh(rounded(1.88, 0.018, 0.018, 0.004), edge, host, 0, 1.86, 0.267);

    // Three small window cards read as software surfaces, not a compute rack.
    for (let row = 0; row < 3; row++) {
      const y = 1.64 - row * 0.32;
      physicalBox(1.80, 0.23, 0.035, recess, host, 0, y, 0.268, 0.025);
      mesh(rounded(0.11, 0.11, 0.008, 0.013), row === 0 ? hostLight : quietBlue, host, -0.72, y, 0.293);
      mesh(rounded(0.89 - row * 0.15, 0.025, 0.009, 0.006), whiteInk, host, -0.06 - row * 0.07, y + 0.025, 0.296);
      mesh(rounded(0.53, 0.014, 0.009, 0.004), edge, host, -0.24, y - 0.035, 0.296);
      mesh(rounded(0.15, 0.038, 0.009, 0.008), quietBlue, host, 0.69, y, 0.296);
    }
    // A second offset glass edge suggests versions, never a duplicate app fork.
    physicalBox(2.23, 1.90, 0.035, glass, host, 0.13, 1.30, -0.25, 0.045);

    function tenant(name: string, x: number, finish: THREE.MeshStandardMaterial, subtitle: string) {
      const unit = new THREE.Group();
      unit.position.set(x, -0.34, 1.13);
      assembly.add(unit);
      physicalBox(1.94, 0.17, 1.24, navy, unit, 0, 0.085, 0, 0.07);
      physicalBox(1.77, 0.032, 1.08, alloy, unit, 0, 0.184, 0, 0.025);
      physicalBox(1.64, 0.98, 0.16, face, unit, 0, 0.74, -0.18, 0.07);
      physicalBox(1.62, 0.93, 0.043, glass, unit, 0, 0.75, 0.13, 0.04);
      for (const side of [-0.86, 0.86]) {
        physicalBox(0.055, 1.05, 0.45, alloy, unit, side, 0.72, 0.02, 0.022);
        mesh(rounded(0.014, 0.87, 0.014, 0.004), finish, unit, side, 0.75, 0.253);
      }
      physicalBox(1.77, 0.05, 0.45, alloy, unit, 0, 1.235, 0.02, 0.02);
      engraved(name, 1.77, unit, 0, 1.04, 0.175, name === 'ATLAS' ? '#a9f1fc' : '#b0c6e4', 114);
      engraved(subtitle, 1.81, unit, 0, 0.09, 0.631, '#9ab4cc', 62);
      mesh(rounded(1.48, 0.018, 0.014, 0.004), finish, unit, 0, 0.194, 0.51);
      for (let row = 0; row < 2; row++) {
        physicalBox(1.21, 0.17, 0.028, recess, unit, 0, 0.77 - row * 0.25, 0.186, 0.02);
        mesh(rounded(0.087, 0.086, 0.008, 0.01), finish, unit, -0.44, 0.77 - row * 0.25, 0.205);
        mesh(rounded(0.66 - row * 0.18, 0.018, 0.008, 0.004), whiteInk, unit, 0.07 - row * 0.09, 0.78 - row * 0.25, 0.207);
      }
      return unit;
    }
    tenant('ATLAS', -2.08, atlasLight, 'CUSTOMER A');
    tenant('NOVA', 1.27, quietBlue, 'CUSTOMER B');

    // A real physical gate interrupts the access path before Atlas.
    const gate = new THREE.Group();
    gate.position.set(-0.45, -0.34, 1.20);
    assembly.add(gate);
    for (const side of [-0.49, 0.49]) {
      physicalBox(0.08, 0.83, 0.19, alloy, gate, side, 0.415, 0, 0.025);
      mesh(rounded(0.018, 0.61, 0.012, 0.004), gateLight, gate, side, 0.41, 0.106);
    }
    physicalBox(1.11, 0.09, 0.25, alloy, gate, 0, 0.86, 0, 0.035);
    leftDoor = physicalBox(0.32, 0.64, 0.04, cyanGlass, gate, -0.16, 0.40, 0, 0.02);
    rightDoor = physicalBox(0.32, 0.64, 0.04, cyanGlass, gate, 0.16, 0.40, 0, 0.02);
    engraved('HUMAN GATE', 1.52, gate, 0, 1.045, 0.128, '#f0cd99', 80);
    mesh(rounded(0.92, 0.02, 0.035, 0.008), gateLight, gate, 0, 0.913, 0.07);

    // The bounded contract is a small document over the gate, not an AI orb.
    contract = new THREE.Group();
    contract.position.set(-0.45, 1.27, 1.08);
    contract.rotation.y = -0.12;
    assembly.add(contract);
    physicalBox(0.74, 0.52, 0.055, navy, contract, 0, 0, 0, 0.04);
    physicalBox(0.67, 0.45, 0.018, cyanGlass, contract, 0, 0, 0.035, 0.02);
    engraved('CONTRACT', 0.96, contract, 0, 0.10, 0.05, '#a8e4f0', 82);
    for (let row = 0; row < 2; row++) mesh(rounded(0.34 - row * 0.09, 0.016, 0.008, 0.004), whiteInk, contract, -0.03, -0.025 - row * 0.075, 0.051);

    // Unsupported code work is visibly separate and stops inside a review bay.
    const engineering = new THREE.Group();
    engineering.position.set(2.65, -0.34, -1.11);
    assembly.add(engineering);
    physicalBox(1.31, 0.17, 1.20, navy, engineering, 0, 0.085, 0, 0.065);
    physicalBox(1.20, 0.027, 1.09, alloy, engineering, 0, 0.186, 0, 0.025);
    physicalBox(1.04, 0.80, 0.12, face, engineering, 0, 0.62, 0.0, 0.035);
    physicalBox(0.99, 0.76, 0.032, glass, engineering, 0, 0.62, 0.10, 0.025);
    mesh(rounded(0.97, 0.018, 0.014, 0.005), engineeringLight, engineering, 0, 1.032, 0.082);
    engraved('ENGINEERING', 1.70, engineering, 0, 1.205, 0.18, '#e5bd86', 81);
    engraved('NO AUTO RELEASE', 1.44, engineering, 0, 0.083, 0.611, '#b7a38a', 53);
    engraved('</>', 0.88, engineering, 0, 0.76, 0.129, '#eac494', 72);
    for (let row = 0; row < 3; row++) {
      mesh(rounded(0.54 - row * 0.06, 0.018, 0.009, 0.004), row === 1 ? engineeringLight : whiteInk, engineering, -0.015 - row * 0.03, 0.56 - row * 0.08, 0.131);
    }

    function path(points: number[][], finish: THREE.MeshStandardMaterial, thickness: number) {
      const curve = new THREE.CatmullRomCurve3(points.map(([x, y, z]) => new THREE.Vector3(x, y, z)), false, 'centripetal');
      mesh(geometry(new THREE.TubeGeometry(curve, 64, thickness, 8, false)), finish, assembly);
      return curve;
    }
    // Raised optical routes stay in the visible aisle, above the foundation.
    // Atlas passes through the physical gate, never through or behind a tenant.
    accessCurve = path([
      [-0.30, 0.075, -0.42], [-0.41, 0.10, 0.05], [-0.45, 0.075, 0.62],
      [-0.45, 0.075, 1.20], [-0.71, 0.075, 1.49], [-1.23, 0.075, 1.45],
    ], atlasRoute, 0.033);
    path([[0.18, -0.307, -0.63], [0.44, -0.307, -0.21], [1.27, -0.307, 0.11], [1.27, -0.307, 0.57]], quietBlue, 0.016);
    engineeringCurve = path([
      [0.97, 0.62, -0.77], [1.36, 0.80, -0.67], [1.76, 0.76, -0.69], [2.13, 0.30, -0.96],
    ], engineeringRoute, 0.031);
    const portGeometry = geometry(new THREE.SphereGeometry(0.058, 12, 8));
    mesh(portGeometry, atlasRoute, assembly, -0.30, 0.075, -0.42);
    mesh(portGeometry, atlasRoute, assembly, -1.23, 0.075, 1.45);
    mesh(portGeometry, engineeringRoute, assembly, 0.97, 0.62, -0.77);
    mesh(portGeometry, engineeringRoute, assembly, 2.13, 0.30, -0.96);
    const packetGeometry = geometry(new THREE.SphereGeometry(0.043, 8, 8));
    const packetCyan = material(new THREE.MeshBasicMaterial({ color: 0xb4f6ff, toneMapped: false }));
    const packetAmber = material(new THREE.MeshBasicMaterial({ color: 0xffdca7, toneMapped: false }));
    for (let index = 0; index < 3; index++) accessPackets.push(mesh(packetGeometry, packetCyan, assembly));
    for (let index = 0; index < 2; index++) engineeringPackets.push(mesh(packetGeometry, packetAmber, assembly));

    // Small local optical washes, not a fullscreen bloom pass or particle field.
    const glowCanvas = document.createElement('canvas');
    glowCanvas.width = glowCanvas.height = 128;
    const glowContext = glowCanvas.getContext('2d');
    if (glowContext) {
      const gradient = glowContext.createRadialGradient(64, 64, 2, 64, 64, 64);
      gradient.addColorStop(0, 'rgba(255,255,255,0.75)');
      gradient.addColorStop(0.4, 'rgba(255,255,255,0.16)');
      gradient.addColorStop(1, 'rgba(255,255,255,0)');
      glowContext.fillStyle = gradient;
      glowContext.fillRect(0, 0, 128, 128);
    }
    const glowTexture = new THREE.CanvasTexture(glowCanvas);
    textures.add(glowTexture);
    function wash(color: number, x: number, z: number, size: number) {
      const finish = material(new THREE.MeshBasicMaterial({
        map: glowTexture, color, transparent: true, opacity: 0.05, depthWrite: false,
        blending: THREE.AdditiveBlending, toneMapped: false,
      }));
      const item = mesh(geometry(new THREE.PlaneGeometry(size, size)), finish, assembly, x, -0.323, z);
      item.rotation.x = -Math.PI / 2;
      return finish;
    }
    wash(0x4c9aff, -0.30, -1.0, 3.4).opacity = 0.12;
    atlasWash = wash(0x3ccfee, -2.08, 1.05, 2.55);
    engineeringWash = wash(0xe8aa5e, 2.6, -1.1, 2.05);
    atlasPoint = new THREE.PointLight(0x28b9e4, 0.1, 3, 2);
    atlasPoint.position.set(-2.08, 0.42, 0.7);
    assembly.add(atlasPoint);
    engineeringPoint = new THREE.PointLight(0xefb268, 0.1, 2.5, 2);
    engineeringPoint.position.set(2.3, 0.58, -0.65);
    assembly.add(engineeringPoint);

    canvas.addEventListener('pointerdown', pointerDown);
    canvas.addEventListener('pointermove', pointerMove);
    canvas.addEventListener('pointerup', pointerUp);
    canvas.addEventListener('pointercancel', pointerUp);
    canvas.addEventListener('lostpointercapture', pointerUp);
    canvas.addEventListener('webglcontextlost', contextLost);
    observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();

    return {
      update(next) {
        const wasMoving = continuousSceneMotion(view);
        view = { ...next };
        if (!view.visible) {
          stopFrame();
          requestRender();
          return;
        }
        if (wasMoving !== continuousSceneMotion(view)) stopFrame();
        requestRender();
      },
      reset() {
        yaw = -0.07;
        pitch = 0;
        elapsed = 0;
        requestRender();
      },
      dispose,
    };
  } catch {
    fail();
    return { update: noop, reset: noop, dispose };
  }
}
