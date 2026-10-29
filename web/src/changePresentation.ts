/** Readable names and clock-based history labels. Never used for authorization. */
export function projectName(id: string | null | undefined): string {
  return id === 'atlas-project' ? 'Project Atlas' : id === 'nova-project' ? 'Project Nova' : id || 'Workspace';
}

/** The exact server-owned project name is part of the strict access contract.
 * The selected identity stays in its structured field, not in action words. */
export function accessRequestText(project: string): string {
  return `Give this person read-only access to ${project} until the selected expiry.`;
}

export function personName(id: string | null | undefined): string {
  if (!id) return 'No person selected';
  const known: Record<string, string> = {
    'atlas-contractor': 'Atlas contractor', 'nova-contractor': 'Nova contractor',
    'atlas-admin': 'Atlas administrator', 'nova-admin': 'Nova administrator',
    'atlas-engineer': 'Atlas engineer', 'nova-engineer': 'Nova engineer',
  };
  return known[id] || id;
}

export function changeStatus(request: { status: string; kind?: string; expires_at?: string | null }, now = Date.now()): string {
  // An approved request can remain stored as active after its grant expires.
  // Show the time boundary without changing the record or claiming a host read.
  const expiry = request.expires_at ? Date.parse(request.expires_at) : NaN;
  return request.kind === 'access' && request.status === 'active' && Number.isFinite(expiry) && expiry <= now
    ? 'expired' : request.status;
}

export function changeTitle(kind?: string): string {
  return kind === 'access' ? 'Temporary access' : kind === 'feature' ? 'Feature request' : 'Customer request';
}
