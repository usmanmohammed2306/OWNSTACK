/** Display labels describe saved state, never grant permission. */
export function requestLabel(status: string): string {
  const labels: Record<string, string> = {
    new: 'Needs preparation', interpreting: 'Preparing', awaiting_approval: 'Ready for review',
    active: 'Approved', engineering: 'Code review', refused: 'Not supported', failed: 'Needs attention',
    revoked: 'Revoked', expired: 'Expired',
  };
  return labels[status] || status.replaceAll('_', ' ');
}

export function requestSteps(status: string, hasProposal: boolean, previewMatches: boolean) {
  const approved = hasApprovalHistory(status);
  const prepared = hasProposal || approved;
  return [
    { label: 'Saved', done: true },
    { label: 'Prepared', done: prepared },
    { label: 'Previewed', done: approved || (prepared && previewMatches) },
    { label: 'Approved', done: approved },
  ];
}

/** A saved preview remains historical after approval, even after revoke/expiry. */
export function hasApprovalHistory(status: string, proposalStatus?: string): boolean {
  return proposalStatus === 'approved' || ['active', 'revoked', 'expired'].includes(status);
}

/** Navigation is a presentation choice; server role checks remain authoritative. */
export function primaryDestinations(role: string): string[] {
  if (role === 'contractor') return ['demo', 'journey'];
  if (role === 'product_owner') return ['demo', 'convergence'];
  if (role === 'engineer') return ['demo', 'journey', 'engineering'];
  return ['demo', 'journey', 'access'];
}
