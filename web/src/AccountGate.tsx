import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Eye, EyeOff, Layers3, ShieldCheck, Ticket, Users } from 'lucide-react';
import { boundedResponse, type BoundedResponse } from './responseDeadline';
import { accountResponse } from './accountResponse';

export type CustomerSession = { user_id: string; tenant_id: string; role: string; ai_mode: string; csrf_token: string; release_assurance_enabled?:boolean;
  workspace_name?: string; display_name?: string; project_id?: string | null; project_name?: string | null;
  scope_version?:string;teams?:{id:string;name:string}[];projects?:{id:string;name:string;team_id:string}[] };
type Transport = <T>(path: string, options?: RequestInit) => Promise<T>;

/** Real session cookies come from the host. No credentials enter browser storage. */
export function AccountGate({ request, ready, signedIn }: {
  request: Transport; ready: boolean; signedIn: (session: CustomerSession) => void;
}) {
  const [mode, setMode] = useState<'login' | 'signup' | 'join'>('login');
  const [signupStep, setSignupStep] = useState(1);
  const [username, setUsername] = useState(''), [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState(''), [name, setName] = useState(''), [workspace, setWorkspace] = useState('');
  const [token, setToken] = useState(''), [invite, setInvite] = useState<{workspace: string;role: string;team?:string} | null>(null);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [show, setShow] = useState(false);
  const [signupEnabled, setSignupEnabled] = useState<boolean | null>(null);
  const active = useRef<BoundedResponse<unknown> | null>(null), mounted = useRef(false), writing = useRef(false);
  useEffect(() => {
    let current = true;
    mounted.current = true;
    const pending = boundedResponse(signal => request<{signup_enabled:boolean}>('/v1/accounts/config', {signal}));
    active.current = pending;
    pending.promise.then(result => { if (current) setSignupEnabled(result.signup_enabled); })
      .catch(() => { if (current) setSignupEnabled(false); });
    return () => { current = false; mounted.current = false; active.current?.cancel(); };
  }, []);
  function change(next: typeof mode) {
    if (writing.current) return;
    setMode(next); setSignupStep(1); setPassword(''); setConfirmation(''); setError(''); setShow(false); setInvite(null); setToken('');
  }
  async function submit() {
    if (writing.current || !ready) return;
    if (mode !== 'login' && password !== confirmation) { setError('The passphrases do not match.'); return; }
    writing.current = true; setBusy(true); setError('');
    const path = mode === 'login' ? '/v1/session' : mode === 'signup' ? '/v1/accounts/signup' : '/v1/accounts/join';
    const body = mode === 'login' ? {username:username.trim().toLowerCase(),password} :
      {username:username.trim().toLowerCase(),password,name,...(mode === 'signup' ? {workspace} : {token:token.trim()})};
    const pending = accountResponse(signal => request<CustomerSession>(path, {method:'POST',body:JSON.stringify(body),signal}));
    active.current = pending;
    try {
      const session = await pending.promise;
      if (!mounted.current) return;
      setPassword(''); setConfirmation(''); setToken(''); signedIn(session);
    } catch (failure) { if (mounted.current) setError(String(failure)); }
    finally { writing.current = false; if (mounted.current) setBusy(false); }
  }
  async function inspect() {
    if (writing.current) return;
    writing.current = true; setBusy(true); setError('');
    const pending = boundedResponse(signal => request<{workspace:string;role:string}>('/v1/accounts/invitations/inspect',
      {method:'POST',body:JSON.stringify({token:token.trim()}),signal})); active.current = pending;
    try { const result = await pending.promise; if (mounted.current) setInvite(result); }
    catch (failure) { if (mounted.current) setError(String(failure)); }
    finally { writing.current = false; if (mounted.current) setBusy(false); }
  }
  const joining = mode === 'join' && !invite;
  const workspaceStep = mode === 'signup' && signupStep === 1;
  return <div className="login-shell"><section className="login-card account-gate" aria-labelledby="account-title">
    <div className="brand"><span className="brand-mark"><Layers3 size={23}/></span><span>OwnStack</span></div>
    <div className="account-mode-icon">{mode === 'join' ? <Ticket size={23}/> : mode === 'signup' ? <Users size={23}/> : <ShieldCheck size={23}/>}</div>
    <h1 id="account-title">{mode === 'login' ? 'Welcome back.' : mode === 'signup' ? workspaceStep ? 'Make it yours.' : 'Your account.' : 'Join your team.'}</h1>
    <p className="muted">{mode === 'login' ? 'Sign in to your workspace.' : mode === 'signup' ? workspaceStep ? 'Create your private customer workspace.' : `Set up your sign-in for ${workspace}.` : invite ? `${invite.workspace} · ${invite.role}` : 'Enter the invitation your administrator shared.'}</p>
    {mode === 'signup' && <div className="account-steps" aria-label={`Step ${signupStep} of 2`}><span className={signupStep === 1 ? 'current' : ''}/><span className={signupStep === 2 ? 'current' : ''}/></div>}
    <form onSubmit={event => { event.preventDefault(); if (workspaceStep) { setSignupStep(2); setError(''); } else void (joining ? inspect() : submit()); }}>
      {joining ? <label>Invitation code<input required minLength={32} maxLength={128} value={token} autoComplete="off" spellCheck={false} onChange={e=>setToken(e.target.value)}/></label> : <>
        {workspaceStep && <label>Workspace name<input required minLength={2} maxLength={80} value={workspace} autoComplete="organization" placeholder="Your company or team" onChange={e=>setWorkspace(e.target.value)}/></label>}
        {(workspaceStep || mode === 'join') && <label>Your name<input required maxLength={100} value={name} autoComplete="name" onChange={e=>setName(e.target.value)}/></label>}
        {!workspaceStep && <>
        <label>Username<input required minLength={mode === 'login' ? 1 : 3} maxLength={40} pattern={mode === 'login' ? undefined : '[a-z0-9][a-z0-9_.-]{2,39}'}
          value={username} autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder={mode === 'login' ? 'Your username' : 'Choose a unique username'} onChange={e=>setUsername(e.target.value.toLowerCase())}/></label>
        <label>Passphrase<span className="password-field"><input required minLength={mode === 'login' ? 1 : 16} maxLength={mode === 'login' ? 256 : 128}
          value={password} type={show ? 'text' : 'password'} autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          placeholder={mode === 'login' ? undefined : 'At least 16 characters'} onChange={e=>setPassword(e.target.value)}/>
          <button type="button" aria-label={show ? 'Hide passphrase' : 'Show passphrase'} onClick={()=>setShow(value=>!value)}>{show ? <EyeOff size={16}/> : <Eye size={16}/>}</button></span></label>
        {mode !== 'login' && <label>Confirm passphrase<input required minLength={16} maxLength={128} type={show ? 'text' : 'password'} autoComplete="new-password" value={confirmation} onChange={e=>setConfirmation(e.target.value)}/></label>}
        </>}
      </>}
      {error && <p className="alert error" role="alert">{error}</p>}
      {busy && <p className="tiny" role="status">{joining ? 'Checking invitation…' : mode === 'login' ? 'Signing in…' : 'Creating your account…'}</p>}
      <button className="primary wide" disabled={busy || !ready || (mode === 'signup' && signupEnabled !== true)}>
        {!ready ? 'Restoring session…' : joining || workspaceStep ? 'Continue' : mode === 'login' ? 'Sign in' : mode === 'signup' ? 'Create workspace' : 'Create account'}<ArrowRight size={16}/></button>
    </form>
    {mode === 'signup' && <p className="tiny">No payment details. AI requires workspace activation.</p>}
    {mode === 'login' && <details className="account-help"><summary>Need help signing in?</summary><p className="tiny">Use your username. Your workspace administrator can arrange a password reset. Email recovery is not configured.</p></details>}
    <div className="account-links">
      {mode === 'signup' && signupStep === 2 && <button className="text-button" disabled={busy} onClick={()=>{setSignupStep(1);setPassword('');setConfirmation('');setError('');}}>Back to workspace details</button>}
      {mode !== 'login' && <button disabled={busy} className="text-button" onClick={()=>change('login')}>Already have an account? Sign in</button>}
      {mode !== 'signup' && signupEnabled === true && <button disabled={busy} className="text-button" onClick={()=>change('signup')}>Create a workspace<ArrowRight size={13}/></button>}
      {mode !== 'join' && <button disabled={busy} className="text-button" onClick={()=>change('join')}>Have an invitation? Join your team</button>}
      {mode === 'signup' && signupEnabled === false && <p className="tiny">Workspace registration is closed. Ask your administrator for an invitation.</p>}
    </div>
  </section></div>;
}
