import { useEffect, useId, useRef, useState } from 'react';
import { boundedResponse, type BoundedResponse } from './responseDeadline';

type Preview = {
  variation_id: string; project_id: string; viewer_id: string; preview_hash: string;
  can_revoke: boolean; before: { allowed: boolean }; after: { allowed: boolean };
  evaluated_at: string; notice: string;
};
export function RevokeReview({ variation, disabled, request, onChanged }: {
  variation: { id: string; project_id: string; viewer_id: string }; disabled: boolean;
  request: <T>(path: string, options?: RequestInit) => Promise<T>; onChanged: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useId();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const pending = useRef<BoundedResponse<unknown> | null>(null);
  const key = useRef('');
  useEffect(() => () => { generation.current++; pending.current?.cancel(); }, []);
  function reset() {
    generation.current++; pending.current?.cancel(); pending.current = null;
    setPreview(null); setAcknowledged(false); setBusy(false); setError('');
  }
  async function load() {
    if (pending.current) return;
    const version = ++generation.current;
    setPreview(null); setAcknowledged(false); setError(''); setBusy(true);
    key.current = crypto.randomUUID();
    const operation = boundedResponse(signal => request<Preview>(
      `/v1/variations/${encodeURIComponent(variation.id)}/revoke-preview`, { signal }));
    pending.current = operation;
    try {
      const result = await operation.promise;
      if (version !== generation.current) return;
      if (result.variation_id !== variation.id || result.project_id !== variation.project_id
          || result.viewer_id !== variation.viewer_id || !/^[a-f0-9]{64}$/.test(result.preview_hash)) {
        throw new Error('Rollback preview identity did not match. Refresh it.');
      }
      setPreview(result);
    } catch (err) { if (version === generation.current) setError(String(err)); }
    finally { if (version === generation.current) { pending.current = null; setBusy(false); } }
  }
  async function confirm() {
    if (pending.current || !acknowledged || !preview?.can_revoke) return;
    const version = ++generation.current;
    setBusy(true); setError('');
    const operation = boundedResponse(signal => request(
      `/v1/variations/${encodeURIComponent(variation.id)}/revoke`, { method: 'POST', signal,
        headers: { 'Idempotency-Key': key.current }, body: JSON.stringify({ preview_hash: preview.preview_hash }) }));
    pending.current = operation;
    try {
      await operation.promise;
      if (version !== generation.current) return;
      dialog.current?.close();
      await onChanged();
    } catch (err) {
      if (version === generation.current) {
        setError(String(err) + ' Refresh saved state and preview again; a timed-out write may have completed.');
        setPreview(null); setAcknowledged(false);
      }
    } finally { if (version === generation.current) { pending.current = null; setBusy(false); } }
  }
  return <><button className="secondary" disabled={disabled} onClick={() => {
    dialog.current?.showModal(); void load();
  }}>Review revoke</button>
    <dialog className="approval-dialog" ref={dialog} aria-labelledby={title} onClose={reset}
      onCancel={event => { if (busy) event.preventDefault(); }}>
      <h2 id={title}>Revoke this exact grant?</h2>
      <p>{variation.viewer_id} · {variation.project_id}</p><p className="tiny">Grant {variation.id}</p>
      {busy && <p role="status">Checking or saving the exact rollback…</p>}
      {error && <p role="alert" className="alert error">{error}</p>}
      {preview && <><div className="comparison"><div><small>BEFORE</small><strong>{preview.before.allowed ? 'Allowed' : 'Denied'}</strong></div>
        <div><small>AFTER THIS REVOKE</small><strong>{preview.after.allowed ? 'Still allowed' : 'Denied'}</strong></div></div>
        {preview.after.allowed && <p className="alert notice">Another grant or role still permits access. This is not a complete offboarding action.</p>}
        <p className="tiny">{preview.notice}</p>
        <p className="tiny">Checked {new Date(preview.evaluated_at).toLocaleString()}. The server rejects changed snapshots.</p>
        <details><summary>Exact rollback snapshot</summary><code>{preview.preview_hash}</code></details>
        {!preview.can_revoke && <p>This grant is no longer active. Refresh workspace state.</p>}
        <label className="approval-ack"><input type="checkbox" checked={acknowledged} disabled={busy || !preview.can_revoke}
          onChange={event => setAcknowledged(event.target.checked)}/> I reviewed this grant and the predicted effect.</label></>}
      <div className="button-row"><button className="primary" disabled={busy || !preview?.can_revoke || !acknowledged}
        onClick={confirm}>Confirm revoke</button>
        <button className="secondary" disabled={busy} onClick={load}>Refresh preview</button>
        <button className="secondary" disabled={busy} onClick={() => dialog.current?.close()}>Cancel</button></div>
    </dialog></>;
}
