/** Saved progress transport, not a proxy for raw model tokens or reasoning. */
import { boundedResponse } from './responseDeadline.ts';

export type ProgressScope = { tenant_id: string; request_id: string; project_id: string; attempt_id: string; revision: number };
export type ProgressSnapshot = ProgressScope & {
  sequence: number; state: string; deadline_elapsed: boolean; phase: string;
  received_bytes: number; deltas: number; source: string; terminal: boolean;
  response: { proposal_id: string; route: string } | null;
};
export type EndCode = 'complete' | 'scope_changed' | 'session_changed' | 'unavailable' | 'wait_limit';
const states = ['queued', 'running', 'accepted', 'failed', 'timed_out', 'canceled', 'superseded'];
const terminals = ['accepted', 'failed', 'timed_out', 'canceled', 'superseded'];
const codes = ['complete', 'scope_changed', 'session_changed', 'unavailable', 'wait_limit'];
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).sort().join() === [...keys].sort().join();
const integer = (v: unknown, max: number) => Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max;

export function validateProgress(value: unknown, scope: ProgressScope, previous: ProgressSnapshot | null): ProgressSnapshot {
  if (!record(value) || !exact(value, ['tenant_id', 'request_id', 'project_id', 'attempt_id', 'revision',
    'sequence', 'state', 'deadline_elapsed', 'phase', 'received_bytes', 'deltas', 'source', 'terminal', 'response'])
    || Object.entries(scope).some(([k, v]) => value[k] !== v)
    || !integer(value.sequence, 52) || (value.sequence as number) <= (previous?.sequence || 0)
    || !states.includes(value.state as string) || typeof value.deadline_elapsed !== 'boolean'
    || !['not_streamed', 'receiving', 'validated'].includes(value.phase as string)
    || !['saved_status', 'fixture_stream', 'provider_stream'].includes(value.source as string)
    || !integer(value.received_bytes, 16_384) || !integer(value.deltas, 512)
    || value.terminal !== terminals.includes(value.state as string)
    || (value.phase === 'not_streamed') !== (value.source === 'saved_status')
    || (previous && ((value.received_bytes as number) < previous.received_bytes || (value.deltas as number) < previous.deltas))) {
    throw new Error('Invalid or changed progress scope. Read saved state before reconnecting.');
  }
  if (value.response !== null && (!record(value.response) || !exact(value.response, ['proposal_id', 'route'])
    || typeof value.response.proposal_id !== 'string' || value.response.proposal_id.length > 40
    || !value.response.proposal_id || !['configure', 'engineering', 'refuse'].includes(value.response.route as string)
    || value.state !== 'accepted')) throw new Error('Invalid saved response.');
  return value as unknown as ProgressSnapshot;
}

export function openProgress(request: (signal: AbortSignal) => Promise<Response>, scope: ProgressScope,
                             onSnapshot: (value: ProgressSnapshot) => void, timeoutMs = 30_000) {
  return boundedResponse(async signal => {
    const response = await request(signal);
    if (signal.aborted) throw new Error('Progress wait stopped locally.');
    if (!response.ok || response.headers.get('content-type')?.split(';')[0] !== 'text/event-stream' || !response.body)
      throw new Error('Progress unavailable. Read saved state or sign in again.');
    const reader = response.body.getReader();
    const abort = () => { void reader.cancel().catch(() => {}); };
    signal.addEventListener('abort', abort, { once: true });
    let buffer = '', bytes = 0, frames = 0, last: ProgressSnapshot | null = null;
    const decoder = new TextDecoder('utf-8', { fatal: true });
    try {
      while (!signal.aborted) {
        const { done, value } = await reader.read();
        if (signal.aborted) throw new Error('Progress wait stopped locally.');
        if (done) throw new Error('Progress ended without a completion frame. Read saved state.');
        bytes += value.byteLength;
        if (bytes > 65_536) throw new Error('Progress response exceeded its byte limit.');
        buffer += decoder.decode(value, { stream: true });
        let end: number;
        while ((end = buffer.indexOf('\n\n')) !== -1) {
          const block = buffer.slice(0, end); buffer = buffer.slice(end + 2);
          if (block.length > 4096 || ++frames > 53) throw new Error('Progress frame limit exceeded.');
          const lines = block.split('\n');
          if (lines.length !== 2 || !lines[0].startsWith('event: ') || !lines[1].startsWith('data: '))
            throw new Error('Malformed progress frame.');
          const event = lines[0].slice(7), data: unknown = JSON.parse(lines[1].slice(6));
          if (event === 'end') {
            if (!record(data) || !exact(data, ['code']) || !codes.includes(data.code as string)
              || (data.code === 'complete' && !last?.terminal)) throw new Error('Invalid progress ending.');
            return data.code as EndCode;
          }
          if (event !== 'snapshot' || last?.terminal) throw new Error('Unexpected progress event.');
          last = validateProgress(data, scope, last);
          if (!signal.aborted) onSnapshot(last);
        }
        if (buffer.length > 4096) throw new Error('Progress frame limit exceeded.');
      }
      throw new Error('Progress wait stopped locally.');
    } finally {
      signal.removeEventListener('abort', abort);
      void reader.cancel().catch(() => {});
    }
  }, timeoutMs);
}
