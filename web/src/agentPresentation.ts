import type { InvestigationRun } from './investigationView';

/** Presentation only. A saved agent conclusion never means access or code shipped. */
export function agentPresentation(run: InvestigationRun | null, live: boolean, capped: boolean, busy: boolean, feature = false) {
  const sources = new Set(run?.steps.filter(s => s.action.startsWith('inspect_')).map(s => s.source));
  const complete = run?.state === 'completed';
  const title = complete ? run.result?.handoff === 'review_code' ? 'This needs a code change'
    : run.result?.handoff === 'clarify_request' ? 'A little more detail is needed' : 'Ready to prepare your preview'
    : busy || run?.state === 'running' ? 'Looking into your request'
    : run && ['failed', 'stopped', 'stale'].includes(run.state) ? 'Investigation needs attention'
    : !live || capped ? 'Your request is saved' : 'Let’s find the right path';
  const description = complete ? 'Saved advice. Applying a change needs a separate review.'
    : busy ? 'Each finished step is saved as the agent works.'
    : !live ? 'AI is paused. You can still review saved work.'
    : capped ? 'The approved AI allowance is used up. Saved work is still available.'
    : 'The agent checks your request and the relevant app rules.';
  return { title, description, complete, nodes: [
    { id: 'request', label: 'Understand', detail: 'Your request', done: sources.has('request') },
    { id: 'evidence', label: 'Investigate', detail: feature || sources.has('engineering') ? 'Code evidence' : 'App rules', done: sources.has('contract') || sources.has('engineering') },
    { id: 'conclude', label: 'Recommend', detail: 'Next step', done: !!complete },
  ] };
}
