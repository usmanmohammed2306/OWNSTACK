type Destination = 'demo' | 'journey' | 'access' | 'engineering' | 'convergence' | 'ledger';
type SavedRequest = { id: string; text: string; status: string; kind?: string; expires_at?: string | null };
/** A compact workspace heading leaves the application model as the primary view. */
export function WorkspaceHome({ tenant, workspaceName }: {
  tenant: string; workspaceName?: string; role: string; requests: SavedRequest[];
  loaded: boolean; navigate: (tab: Destination) => void;
  newRequest: (kind?: 'access' | 'feature', text?: string) => void; selectRequest: (id: string) => void;
}) {
  const name = workspaceName || (tenant === 'nova' ? 'Nova' : tenant === 'atlas' ? 'Atlas' : tenant === 'platform' ? 'Platform' : tenant);
  return <div className="spatial-home">
    <section className="spatial-title" aria-labelledby="home-title">
      <p>WORKSPACE</p><h2 id="home-title">{name}</h2>
    </section>
  </div>;
}
