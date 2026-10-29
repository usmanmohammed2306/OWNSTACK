/** Use server time so a workstation's clock cannot prolong a visible grant. */
export function accessRefreshDelay(snapshot:{as_of:string;rules:{expires_at:string|null}[]}):number{
  const now=Date.parse(snapshot.as_of);
  if(!Number.isFinite(now))return 1000;
  const deadlines=snapshot.rules.map(r=>r.expires_at?Date.parse(r.expires_at)-now:Infinity).filter(n=>Number.isFinite(n)&&n>0);
  return Math.max(100,Math.min(15_000,...deadlines));
}
