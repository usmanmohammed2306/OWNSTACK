import test from 'node:test';
import assert from 'node:assert/strict';
import { continuousSceneMotion } from '../src/sceneMotion.ts';

test('continuous motion requires visibility, user permission and no reduced-motion preference', () => {
  for (const motion of [false, true]) {
    for (const reducedMotion of [false, true]) {
      for (const visible of [false, true]) {
        assert.equal(continuousSceneMotion({ motion, reducedMotion, visible }), motion && !reducedMotion && visible);
      }
    }
  }
});
