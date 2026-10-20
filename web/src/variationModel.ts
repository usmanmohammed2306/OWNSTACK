/**
 * Display-only illustration of OwnStack's boundaries, never live request state.
 * Selecting a stage does not preview, approve, grant, revoke, run checks or deploy.
 * The host API remains authoritative for every real protected read.
 */
export type Scenario = 'access' | 'pdf';
export type Stage = 0 | 1 | 2 | 3;

export type VariationFrame = {
  atlas: 'unchanged' | 'preview' | 'temporary' | 'revoked';
  nova: 'unchanged';
  route: 'contract' | 'atlas' | 'engineering' | 'closed';
  gate: 'required' | 'illustrated-approval';
  sharedAppCount: 1;
  deployed: false;
};

export type VariationStageContent = {
  name: string;
  title: string;
  description: string;
  atlasLabel: string;
  novaLabel: string;
  gateLabel: string;
};

type ScenarioContent = {
  title: string;
  kicker: string;
  stages: readonly [VariationStageContent, VariationStageContent, VariationStageContent, VariationStageContent];
};

/** Invalid numbers return to the initial illustration, never to an approval. */
export function variationFrame(scenario: Scenario, stage: number): VariationFrame {
  const boundedStage = Number.isFinite(stage) ? Math.min(3, Math.max(0, Math.floor(stage))) as Stage : 0;
  const base = { nova: 'unchanged', sharedAppCount: 1, deployed: false } as const;

  if (scenario === 'pdf') {
    return { ...base, atlas: 'unchanged', route: 'engineering', gate: 'required' };
  }

  switch (boundedStage) {
    case 1:
      return { ...base, atlas: 'preview', route: 'contract', gate: 'required' };
    case 2:
      return { ...base, atlas: 'temporary', route: 'atlas', gate: 'illustrated-approval' };
    case 3:
      return { ...base, atlas: 'revoked', route: 'closed', gate: 'illustrated-approval' };
    default:
      return { ...base, atlas: 'unchanged', route: 'contract', gate: 'required' };
  }
}

export const scenarioContent: Record<Scenario, ScenarioContent> = {
  access: {
    title: 'Give a contractor read-only Atlas access until Friday.',
    kicker: 'Temporary access',
    stages: [
      {
        name: 'Contract',
        title: 'A narrow change. A shared app.',
        description: 'A versioned Capability Contract bounds one contractor, Project Atlas, read-only access and an expiry. No customer fork is created.',
        atlasLabel: 'Unchanged',
        novaLabel: 'Unchanged',
        gateLabel: 'Admin approval required',
      },
      {
        name: 'Preview',
        title: 'See the effect before permission changes.',
        description: 'The host computes a counterfactual using its read policy. A preview is not an observed read and does not grant access.',
        atlasLabel: 'Preview only',
        novaLabel: 'Unchanged',
        gateLabel: 'Admin approval required',
      },
      {
        name: 'Atlas only',
        title: 'One customer changes. Nova does not.',
        description: 'This illustrates exact admin approval followed by host-enforced, temporary Atlas access. The host checks scope, expiry and revocation on every read.',
        atlasLabel: 'Temporary read-only',
        novaLabel: 'Unchanged',
        gateLabel: 'Approval illustrated',
      },
      {
        name: 'Rollback',
        title: 'Remove the variation. Keep the app.',
        description: 'Revocation or expiry closes the temporary access path. The next protected read is denied; the shared app and Nova stay unchanged.',
        atlasLabel: 'Access revoked',
        novaLabel: 'Unchanged',
        gateLabel: 'Prior approval illustrated',
      },
    ],
  },
  pdf: {
    title: 'Add PDF export for this customer.',
    kicker: 'Engineering change',
    stages: [
      {
        name: 'Boundary',
        title: 'A new feature is not a permission flag.',
        description: 'PDF export is outside the access contract. It becomes an engineering work item, without changing either tenant.',
        atlasLabel: 'Unchanged',
        novaLabel: 'Unchanged',
        gateLabel: 'Human decision required',
      },
      {
        name: 'Diff',
        title: 'Review the exact proposed code.',
        description: 'The Engineer Cockpit exposes the request and bounded source diff. An AI or manual draft is a proposal, not a release.',
        atlasLabel: 'Unchanged',
        novaLabel: 'Unchanged',
        gateLabel: 'Human decision required',
      },
      {
        name: 'Checks',
        title: 'Check the patch independently.',
        description: 'Fixed checks run against the exact patch in a disposable copy. Failures stay visible. A passing test is not a security guarantee or deployment.',
        atlasLabel: 'Unchanged',
        novaLabel: 'Unchanged',
        gateLabel: 'Human decision required',
      },
      {
        name: 'Handoff',
        title: 'A human owns the release decision.',
        description: 'An engineer can accept for manual release, reject or take over with AI off. Recording that choice does not merge or deploy the patch.',
        atlasLabel: 'Unchanged',
        novaLabel: 'Unchanged',
        gateLabel: 'Human decision required',
      },
    ],
  },
};
