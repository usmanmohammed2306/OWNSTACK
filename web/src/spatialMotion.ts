/** Stable bounded spring for decorative transforms, never workflow state. */
export function springStep(position: number, velocity: number, target: number, seconds: number) {
  if (![position, velocity, target, seconds].every(Number.isFinite)) return { position: 0, velocity: 0, settled: true };
  const dt = Math.min(Math.max(seconds, 0), 1 / 30);
  const nextVelocity = velocity + ((target - position) * 125 - velocity * 22) * dt;
  const nextPosition = position + nextVelocity * dt;
  const settled = Math.abs(target - nextPosition) < .0005 && Math.abs(nextVelocity) < .0005;
  return settled ? { position: target, velocity: 0, settled } : { position: nextPosition, velocity: nextVelocity, settled };
}
