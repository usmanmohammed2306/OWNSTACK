export type SceneMotion = { motion: boolean; reducedMotion: boolean; visible: boolean };

/** Visibility and the operating-system preference take precedence over animation. */
export function continuousSceneMotion(view: SceneMotion): boolean {
  return view.motion && !view.reducedMotion && view.visible;
}
