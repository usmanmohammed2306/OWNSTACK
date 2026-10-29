import { useEffect, useRef, useState } from 'react';
import { ArrowUp, AudioLines, Check, LoaderCircle, Mic, X, Move, Palette, Compass, FilePlus2 } from 'lucide-react';
import { parseCommandPlan, type CommandPlan } from './commandPlan';
import { parseSavedCommand,commandStateMessage,type PlannerReply,type PlannerTransport,type SavedCommand } from './plannerState';

type Recognition = {lang:string;continuous:boolean;interimResults:boolean;onresult:((e:{results:{[index:number]:{[index:number]:{transcript:string}}}})=>void)|null;onerror:((e:{error:string})=>void)|null;onend:(()=>void)|null;start:()=>void;abort:()=>void};
type RecognitionWindow = Window & {SpeechRecognition?:new()=>Recognition;webkitSpeechRecognition?:new()=>Recognition};
export function AgentCommand({role,identityKey,transport,preview,apply,onState}: {role:string;identityKey:string;transport:PlannerTransport;onState?:(state:'idle'|'working'|'review'|'error')=>void;
  preview:(plan:CommandPlan|null)=>void;apply:(plan:CommandPlan,text:string)=>boolean}) {
  const [text,setText]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [plan,setPlan]=useState<CommandPlan|null>(null),[voiceConsent,setVoiceConsent]=useState(false),[listening,setListening]=useState(false);
  const sequence=useRef(0),controller=useRef<AbortController|null>(null),speech=useRef<Recognition|null>(null);
  const input=useRef<HTMLInputElement>(null);
  const [run,setRun]=useState<PlannerReply|null>(null);
  const recovery=useRef<SavedCommand|null>(null),poll=useRef<ReturnType<typeof setTimeout>|null>(null);
  const storageKey='ownstack:planner:'+identityKey;
  const latest=useRef({preview,transport});latest.current={preview,transport};
  useEffect(()=>{onState?.(busy?'working':plan?'review':error?'error':'idle');},[busy,plan,error]);
  function remember(value:SavedCommand|null){recovery.current=value;try{if(value)sessionStorage.setItem(storageKey,JSON.stringify(value));else sessionStorage.removeItem(storageKey);}catch{/* Server state survives disabled browser storage. */}}
  function present(result:PlannerReply,mine:number){
    if(mine!==sequence.current)return;
    setRun(result);if(result.text)setText(result.text);
    if(recovery.current)remember({...recovery.current,generation:result.generation});
    if(result.status==='running'){
      setBusy(true);poll.current=setTimeout(()=>{const key=recovery.current?.key,signal=controller.current?.signal;if(key&&signal)void latest.current.transport.read(key,signal).then(r=>present(r,mine)).catch(()=>{if(mine===sequence.current){setBusy(false);setError('Could not refresh saved progress. Check its status again; no new generation was started.');}});},1000);return;
    }
    setBusy(false);
    if(result.status!=='accepted'){setError(commandStateMessage(result));return;}
    const parsed=parseCommandPlan(result.plan,role);
    if(!parsed||!result.artifact||!/^[a-f0-9]{64}$/.test(result.artifact)){setError('The saved planner response is invalid. Start a new command.');return;}
    if(parsed.actions[0].action==='refuse')setError('That action requires an authorized review or is outside this workspace.');
    else if(parsed.actions[0].action==='clarify')setError('Name the object and the change you want. This request needs a clearer scope.');
    else {setError('');setPlan(parsed);preview(parsed);}
  }
  useEffect(()=>{
    let stored:SavedCommand|null=null;try{stored=parseSavedCommand(sessionStorage.getItem(storageKey));}catch{/* Optional browser recovery. */}
    if(stored){recovery.current=stored;const mine=sequence.current,abort=new AbortController();controller.current=abort;setBusy(true);
      void transport.read(stored.key,abort.signal).then(r=>present(r,mine)).catch(()=>{if(mine===sequence.current){setBusy(false);setError('Saved command is not available yet. Refresh to check it; no generation was started.');}});}
    return()=>{sequence.current++;controller.current?.abort();if(poll.current)clearTimeout(poll.current);speech.current?.abort();latest.current.preview(null);};
  },[]);
  useEffect(()=>{const focus=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();input.current?.focus();}};window.addEventListener('keydown',focus);return()=>window.removeEventListener('keydown',focus);},[]);
  function cancel(){const saved=recovery.current;sequence.current++;controller.current?.abort();if(poll.current)clearTimeout(poll.current);setBusy(false);setPlan(null);setRun(null);preview(null);remember(null);
    if(saved&&text.trim())void transport.cancel(text,saved.key,saved.generation).catch(()=>{/* Late browser results remain fenced even if this local stop cannot reach the server. */});}
  async function submit(retrying=false){
    if(!text.trim()||busy||plan)return;
    sequence.current++;controller.current?.abort();if(poll.current)clearTimeout(poll.current);setError('');setBusy(true);
    const mine=sequence.current,abort=new AbortController();controller.current=abort;
    const key=retrying&&recovery.current?recovery.current.key:crypto.randomUUID();remember({key,generation:retrying&&run?run.generation:1});
    const timeout=setTimeout(()=>abort.abort(),60000);
    try{present(retrying&&run?await transport.retry(run.id,run.generation,abort.signal):await transport.start(text,key,abort.signal),mine);}
    catch(e){if(mine===sequence.current){setBusy(false);setError(abort.signal.aborted?'Stopped waiting. The local model may still finish; no action was applied.':e instanceof Error?e.message:'Planning failed.');
      if(!abort.signal.aborted)try{present(await transport.read(key,abort.signal),mine);}catch{/* Preserve the original failure and recovery key. */}}}
    finally{clearTimeout(timeout);}
  }
  function startVoice(){
    const BrowserSpeech=(window as RecognitionWindow).SpeechRecognition||(window as RecognitionWindow).webkitSpeechRecognition;
    if(!BrowserSpeech){setError('Voice input is unavailable in this browser. Type your command.');setVoiceConsent(false);return;}
    const recognition=new BrowserSpeech();speech.current=recognition;recognition.lang='en-US';recognition.continuous=false;recognition.interimResults=false;
    recognition.onresult=e=>{cancel();setText(e.results[0][0].transcript.slice(0,1000));};
    recognition.onerror=()=>{setListening(false);setError('Voice input stopped. Type your command or try again.');};recognition.onend=()=>setListening(false);
    try{recognition.start();setListening(true);setVoiceConsent(false);}catch{setError('Microphone unavailable.');setVoiceConsent(false);}
  }
  const labels={demo:'Workspace',journey:'Requests',access:'Access',engineering:'Code',convergence:'Patterns',ice:'Ice',violet:'Violet',mint:'Mint',feature:'Feature'};
  return <section className="agent-command-dock" aria-label="Workspace assistant">
    {!text&&!plan&&!busy&&<div className="agent-intake-hint"><span>Ask OwnStack</span><kbd>⌘ / Ctrl K</kbd></div>}
    {voiceConsent&&<div className="voice-disclosure"><p>Your browser may send audio to its speech provider. The transcript stays editable before planning.</p><button onClick={startVoice}>Start microphone</button><button onClick={()=>setVoiceConsent(false)}>Cancel</button></div>}
    {plan&&<div className="command-preview" role="region" aria-label="Proposed interaction"><span className="command-preview-label">Preview</span><div>{plan.actions.map((a,i)=>{
      const Icon=a.action==='move'?Move:a.action==='theme'?Palette:a.action==='draft'?FilePlus2:Compass;
      return <span className="command-action" key={i}><Icon size={19}/><strong>{a.action==='reset'?'Default layout':'target'in a?labels[a.target]:a.action}</strong><small>{a.action==='move'?`${a.x}, ${a.z}`:a.action==='draft'?'Open request':a.action==='theme'?'Palette':a.action==='reset'?'Reset':'Open'}</small></span>;
    })}</div><button className="accept-plan" aria-label="Apply proposed interaction" onClick={()=>{if(apply(plan,text)){remember(null);setRun(null);setPlan(null);preview(null);setText('');}else{setError('The workspace changed. Plan this command again.');cancel();}}}><Check size={17}/>Apply</button><button aria-label="Discard proposed interaction" onClick={cancel}><X size={17}/></button></div>}
    {!busy&&run&&['failed','timed_out','cancelled'].includes(run.status)&&run.generation<3&&<button type="button" className="retry-command" onClick={()=>void submit(true)}>Retry saved command</button>}
    {!busy&&run?.status==='running'&&<button type="button" className="retry-command" onClick={()=>{const saved=recovery.current;if(saved){const mine=sequence.current,abort=new AbortController();controller.current=abort;void transport.read(saved.key,abort.signal).then(r=>present(r,mine)).catch(()=>{if(mine===sequence.current)setError('Could not check saved status. Try again.');});}}}>Check saved status</button>}
    {error&&<div className="command-error" role="alert">{error}<button aria-label="Dismiss command error" onClick={()=>setError('')}><X size={13}/></button></div>}
    {run?.attempts?.some(a=>a.status!=='accepted')&&<details className="command-error"><summary>Attempt history ({run.attempts.length})</summary><ol>{run.attempts.map(a=><li key={a.generation}>Attempt {a.generation}: {a.status==='accepted'?'Plan saved':a.status==='timed_out'?'Timed out':a.status==='cancelled'?'Stopped':'Could not finish'}{a.error_code?' · '+a.error_code:''}</li>)}</ol></details>}
    <form onSubmit={e=>{e.preventDefault();void submit();}} onKeyDown={e=>{if(e.key==='Escape'&&(plan||busy)){e.preventDefault();cancel();}}}>
      <AudioLines className="command-glyph" size={20} aria-hidden="true"/>
      <label className="sr-only" htmlFor="workspace-command">Tell OwnStack what you want to do</label>
      <input ref={input} id="workspace-command" value={text} maxLength={1000} autoComplete="off" placeholder="What would you like to change?" onChange={e=>{if(plan||busy)cancel();setText(e.target.value);}}/>
      <button type="button" aria-label={listening?'Stop voice input':'Use voice input'} className={listening?'listening':''} onClick={()=>{if(listening){speech.current?.abort();setListening(false);}else setVoiceConsent(true);}}><Mic size={18}/></button>
      {busy?<button type="button" aria-label="Stop waiting for planner" onClick={cancel}><X size={17}/></button>:<button type="submit" className="agent-send" aria-label="Plan this command" disabled={!text.trim()||!!plan}><ArrowUp size={19}/></button>}
    </form>{busy&&<span className="command-progress" role="status"><LoaderCircle size={12}/>Planning your interaction…</span>}
  </section>;
}
