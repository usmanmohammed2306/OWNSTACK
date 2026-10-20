export function BoundaryMap() {
  return <figure className="system-map" aria-label="Architecture: Nemotron proposes through a human gate. Host policy enforces a scoped Atlas variation while Nova remains outside its scope.">
    <div className="map-caption"><span>EXECUTION BOUNDARY</span><span>CONTRACT v1</span></div>
    <svg viewBox="0 0 540 340" role="img" aria-labelledby="map-title">
      <title id="map-title">Architecture illustration, not a current-state observation</title>
      <defs><pattern id="map-grid" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".8" fill="#315158"/></pattern><linearGradient id="map-edge"><stop stopColor="#51cfd0" stopOpacity=".1"/><stop offset="1" stopColor="#99f4cb"/></linearGradient></defs>
      <rect width="540" height="340" fill="url(#map-grid)"/>
      <circle cx="272" cy="174" r="117" className="map-orbit"/><circle cx="272" cy="174" r="141" className="map-orbit outer"/>
      <path d="M125 99H230Q272 99 272 139V158M272 208V244Q272 266 312 266H357" className="map-path"/>
      <path d="M272 208V244Q272 314 326 314H357" className="map-path excluded"/>
      <g className="map-node"><rect x="20" y="69" width="144" height="59" rx="5"/><text x="36" y="92" className="map-micro">01 / PROPOSE</text><text x="36" y="113">NVIDIA Nemotron</text></g>
      <g className="map-gate"><path d="M272 122L304 147L272 172L240 147Z"/><text x="316" y="143" className="map-micro">HUMAN GATE</text><text x="316" y="160">Exact approval</text></g>
      <g className="map-node host"><rect x="194" y="177" width="156" height="58" rx="5"/><text x="211" y="200" className="map-micro">02 / ENFORCE</text><text x="211" y="220">Host-owned policy</text></g>
      <g className="map-node atlas"><rect x="357" y="241" width="162" height="48" rx="5"/><text x="373" y="260" className="map-micro">ATLAS ONLY</text><text x="373" y="279">Temporary · read-only</text></g>
      <g className="map-node nova"><rect x="357" y="299" width="162" height="32" rx="5"/><text x="373" y="320">Nova · out of scope</text></g>
      <circle cx="272" cy="99" r="4" className="map-point"/><circle cx="339" cy="314" r="4" fill="#8a9ba5"/>
      <text x="20" y="219" className="map-micro">NO MODEL</text><text x="20" y="235" className="map-micro">EXECUTION AUTHORITY</text>
    </svg>
    <figcaption>Architecture illustration. Not a live state visualization.</figcaption>
  </figure>;
}
