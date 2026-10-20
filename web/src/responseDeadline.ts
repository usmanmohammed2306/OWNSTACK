/** Bound the browser's wait, never claim cancellation of a server operation. */
export class LocalResponseWaitError extends Error {
  readonly code: 'timeout' | 'canceled';
  constructor(code: 'timeout' | 'canceled') {
    super(code === 'timeout'
      ? 'The response wait timed out locally. The server may still complete the operation.'
      : 'Stopped waiting locally. Server completion or cancellation is unverified.');
    this.name = 'LocalResponseWaitError';
    this.code = code;
  }
}

export type BoundedResponse<T> = { promise: Promise<T>; cancel: () => void };

/** Also settles when an injected transport ignores AbortSignal. Late data is ignored. */
export function boundedResponse<T>(request: (signal: AbortSignal) => Promise<T>, timeoutMs = 12_000): BoundedResponse<T> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new RangeError('A positive finite response deadline is required');
  const controller = new AbortController();
  let settled = false;
  let resolveWait!: (value: T) => void;
  let rejectWait!: (reason: unknown) => void;
  const promise = new Promise<T>((resolve, reject) => { resolveWait = resolve; rejectWait = reject; });
  const stop = (code: 'timeout' | 'canceled') => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    controller.abort();
    rejectWait(new LocalResponseWaitError(code));
  };
  const timer = setTimeout(() => stop('timeout'), timeoutMs);
  try {
    Promise.resolve(request(controller.signal)).then(value => {
      if (settled) return;
      settled = true; clearTimeout(timer); resolveWait(value);
    }, failure => {
      if (settled) return;
      settled = true; clearTimeout(timer); rejectWait(failure);
    });
  } catch (failure) {
    settled = true; clearTimeout(timer); rejectWait(failure);
  }
  return { promise, cancel: () => stop('canceled') };
}
