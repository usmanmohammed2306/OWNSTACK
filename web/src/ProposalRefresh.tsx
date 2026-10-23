import { useEffect, useId, useRef, useState } from 'react';
import { boundedResponse, type BoundedResponse } from './responseDeadline';
import { matchesRefreshReview, type RefreshIdentity, type RefreshReview } from './refreshIdentity';

export function ProposalRefresh({ identity, canRefresh, disabled, request, onChanged }: {
  identity: RefreshIdentity; canRefresh: boolean; disabled: boolean;
  request: <T>(path: string, options?: RequestInit) => Promise<T>; onChanged: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null), title = useId();
  const [review, setReview] = useState<RefreshReview | null>(null);
  const [acknowledged, setAcknowledged] = useState(false), [busy, setBusy] = useState(false);
  const [reason, setReason] = useState('Host changed; preserve original scope and expiry for fresh admin review.');
  const [error, setError] = useState('');
  const generation = useRef(0), key = useRef('');
  const pending = useRef<BoundedResponse<unknown> | null>(null);
  useEffect(() => () => { generation.current++; pending.current?.cancel(); }, []);
  function reset() {
    generation.current++; pending.current?.cancel(); pending.current = null;
    setReview(null); setAcknowledged(false); setBusy(false); setError('');
  }
  async function load() {
    if (pending.current) return;
    const version = ++generation.current;
    setReview(null); setAcknowledged(false); setError(''); setBusy(true); key.current = crypto.randomUUID();
    const operation = boundedResponse(signal => request<RefreshReview>(
      `/v1/proposals/${encodeURIComponent(identity.proposalId)}/refresh-review`, { signal }));
    pending.current = operation;
    try {
      const result = await operation.promise;
      if (version !== generation.current) return;
      if (!matchesRefreshReview(result, identity)) throw new Error('Review did not match the current identity and proposal.');
      setReview(result);
    } catch (err) { if (version === generation.current) setError(String(err)); }
    finally { if (version === generation.current) { pending.current = null; setBusy(false); } }
  }
  async function confirm() {
    if (pending.current || !canRefresh || !acknowledged || !review?.can_refresh || reason.trim().length < 10) return;
    const version = ++generation.current;
    setBusy(true); setError('');
    const operation = boundedResponse(signal => request(
      `/v1/proposals/${encodeURIComponent(identity.proposalId)}/refresh`, { method: 'POST', signal,
        headers: { 'Idempotency-Key': key.current }, body: JSON.stringify({
          proposal_hash: identity.proposalHash, review_hash: review.review_hash, reason: reason.trim() }) }));
    pending.current = operation;
    try {
      await operation.promise;
      if (version !== generation.current) return;
      dialog.current?.close(); await onChanged();
    } catch (err) {
      if (version === generation.current) {
        setError(String(err) + ' Read saved state before retrying; a timed-out write may have completed.');
        setReview(null); setAcknowledged(false);
      }
    } finally { if (version === generation.current) { pending.current = null; setBusy(false); } }
  }
  return <><button className="secondary" disabled={disabled} onClick={() => {
    dialog.current?.showModal(); void load();
  }}>Recover changed proposal</button>
    <dialog className="approval-dialog" ref={dialog} aria-labelledby={title} onClose={reset}
      onCancel={event => { if (busy) event.preventDefault(); }}>
      <h2 id={title}>New review. Same intent.</h2>
      <p>Recover from changed host data without overwriting the original proposal or calling AI.</p>
      {busy && <p role="status">Checking or saving the reviewed revision…</p>}
      {error && <p role="alert" className="alert error">{error}</p>}
      {review && <>
        <p className={'alert ' + (review.can_refresh ? 'notice' : '')}>{review.can_refresh
          ? 'Host snapshot changed. A new proposal requires fresh admin approval.'
          : 'Host snapshot is unchanged. Keep the existing proposal; no new revision is needed.'}</p>
        <dl className="approval-scope"><div><dt>PROJECT</dt><dd>{review.parameters.project_id}</dd></div>
          <div><dt>CONTRACTOR</dt><dd>{review.parameters.viewer_id}</dd></div>
          <div><dt>UNCHANGED EXPIRY</dt><dd>{new Date(review.parameters.expires_at).toLocaleString()}</dd></div>
          <div><dt>NEXT REVISION</dt><dd>{identity.revision + 1}{!review.can_refresh && ' (not needed)'}</dd></div></dl>
        <p>Current preview would reveal: {review.preview.visible_documents.map(d => d.title).join(', ') || 'no documents'}.</p>
        <details><summary>Compare snapshot identities</summary><p className="tiny">Hashes identify different snapshots, not which individual document changed.</p>
          <div className="hash-line"><span>SAVED PREVIEW</span><code>{review.saved_preview_hash}</code></div>
          <div className="hash-line"><span>CURRENT PREVIEW</span><code>{review.fresh_preview_hash}</code></div></details>
        <p className="tiny">{review.notice}</p>
        {!canRefresh && <p>An engineer must prepare the replacement. Admin approval is still a separate step.</p>}
        {canRefresh && review.can_refresh && <><label>Reason for refresh<textarea value={reason} maxLength={500} disabled={busy}
          onChange={event => { setReason(event.target.value); key.current = crypto.randomUUID(); }}/></label>
          <label className="approval-ack"><input type="checkbox" checked={acknowledged} disabled={busy}
            onChange={event => setAcknowledged(event.target.checked)}/> I reviewed this current snapshot. The scope and expiry stay unchanged; no access is granted.</label></>}
      </>}
      <div className="button-row"><button className="primary" disabled={busy || !canRefresh || !review?.can_refresh || !acknowledged || reason.trim().length < 10}
        onClick={confirm}>Create reviewed revision</button>
        <button className="secondary" disabled={busy} onClick={load}>Recheck host</button>
        <button className="secondary" disabled={busy} onClick={() => dialog.current?.close()}>Cancel</button></div>
    </dialog></>;
}
