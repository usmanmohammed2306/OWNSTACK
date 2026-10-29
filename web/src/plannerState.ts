/** Server records are authoritative; browser storage holds only a recovery key. */
export type PlannerReply={id:string;status:string;generation:number;text?:string;plan?:unknown;artifact?:string;resolution?:string;error_code?:string|null;attempts?:{generation:number;status:string;error_code:string|null}[]};
export type PlannerTransport={
  start:(text:string,key:string,signal:AbortSignal)=>Promise<PlannerReply>;
  read:(key:string,signal:AbortSignal)=>Promise<PlannerReply>;
  retry:(id:string,generation:number,signal:AbortSignal)=>Promise<PlannerReply>;
  cancel:(text:string,key:string,generation:number)=>Promise<PlannerReply>;
};
export type SavedCommand={key:string;generation:number};
export function parseSavedCommand(raw:string|null):SavedCommand|null {
  if(!raw||raw.length>200)return null;
  try{const v=JSON.parse(raw);return v&&typeof v==='object'&&!Array.isArray(v)
    &&Object.keys(v).sort().join(',')==='generation,key'&&typeof v.key==='string'
    &&/^[a-f0-9-]{36}$/.test(v.key)&&Number.isInteger(v.generation)&&v.generation>=1&&v.generation<=3?v:null;}catch{return null;}
}
export function commandStateMessage(run:PlannerReply) {
  if(run.status==='running')return 'Your command is saved and still running.';
  if(run.status==='timed_out')return 'Planning timed out. The local model may still finish; its late result cannot be applied.';
  if(run.status==='cancelled')return 'Stopped locally. Remote model cancellation is not verified.';
  if(run.status==='identity_changed'||run.status==='invalidated')return 'Your account or workspace policy changed. Start a new command.';
  if(run.error_code==='BUSY')return 'The planner is busy. Your command is saved; retry when ready.';
  return 'Planning could not finish. Your saved command is available to retry.';
}
