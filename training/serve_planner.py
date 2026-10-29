"""Loopback-only local inference from an operator-pinned training export.

Never exposes a shell or network tool. No hub publication, remote-code execution,
private app context or provider API key. Start only after checking the evaluation.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, ConfigDict, Field

app=FastAPI(title='OwnStack trained planner',docs_url=None,redoc_url=None)
lock=threading.Lock()
runtime=None
inference_thread=ThreadPoolExecutor(max_workers=1,thread_name_prefix='ownstack-model')

def load():
    root=Path(os.environ['OWNSTACK_PLANNER_ARTIFACT']).resolve()
    manifest=(root/'manifest.json').read_bytes()
    actual=hashlib.sha256(manifest).hexdigest()
    if actual!=os.environ['OWNSTACK_PLANNER_MANIFEST_SHA256']:raise RuntimeError('Training manifest digest mismatch')
    info=json.loads(manifest)
    if info['base_model']!='Qwen/Qwen3-0.6B' or len(info['base_revision'])!=40:raise RuntimeError('Unrecognized base model')
    # Local adapter files are safetensors. No pickle weights or trust_remote_code.
    adapter=root/'adapter'
    if not (adapter/'adapter_model.safetensors').is_file():raise RuntimeError('Missing trained adapter')
    installation=(root/'installation.json').read_bytes()
    if hashlib.sha256(installation).hexdigest()!=os.environ['OWNSTACK_PLANNER_INSTALLATION_SHA256']:raise RuntimeError('Installation digest mismatch')
    expected=json.loads(installation)
    if set(expected['files'])!={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p.name!='installation.json'}:raise RuntimeError('Artifact inventory mismatch')
    for relative,digest in expected['files'].items():
        target=(root/relative).resolve()
        if not target.is_relative_to(root) or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise RuntimeError('Artifact file digest mismatch')
    apple=os.getenv('OWNSTACK_PLANNER_APPLE_PATH')
    if apple:
        converted=Path(apple).resolve();data=(converted/'conversion.json').read_bytes()
        if hashlib.sha256(data).hexdigest()!=os.environ['OWNSTACK_PLANNER_CONVERSION_SHA256']:raise RuntimeError('Conversion digest mismatch')
        conversion=json.loads(data)
        if conversion['source_manifest_sha256']!=actual:raise RuntimeError('Conversion belongs to another training run')
        if not conversion['files']:raise RuntimeError('Empty conversion inventory')
        if set(conversion['files'])!={str(p.relative_to(converted)) for p in (converted/'model').rglob('*') if p.is_file()}:raise RuntimeError('Converted inventory mismatch')
        for relative,digest in conversion['files'].items():
            p=(converted/relative).resolve()
            if not p.is_relative_to(converted) or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise RuntimeError('Converted weight digest mismatch')
        from mlx_lm import load as apple_load
        import mlx.core as mx
        mx.set_cache_limit(128*1024*1024)
        mx.set_memory_limit(2*1024*1024*1024)
        model,tokenizer=apple_load(str(converted/'model'),tokenizer_config={'trust_remote_code':False})
        return 'mlx',tokenizer,model,'apple_metal_8bit',info['system'],actual
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    torch.set_num_threads(2)
    tokenizer=AutoTokenizer.from_pretrained(adapter,local_files_only=True,trust_remote_code=False)
    device='mps' if torch.backends.mps.is_available() else 'cpu'
    dtype=torch.float16 if device=='mps' else torch.float32
    model=AutoModelForCausalLM.from_pretrained(info['base_model'],revision=info['base_revision'],dtype=dtype,trust_remote_code=False,use_safetensors=True)
    model=PeftModel.from_pretrained(model,adapter,local_files_only=True).eval()
    model.to(device=device,dtype=dtype)
    return torch,tokenizer,model,device,info['system'],actual

class Command(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    text:str=Field(min_length=1,max_length=1000)

@app.get('/health')
def health():return {'ready':runtime is not None,'artifact':runtime[-1] if runtime else None,'device':runtime[3] if runtime else None}

def service_identity(x_ownstack_planner_key:str|None=Header(default=None)):
    expected=os.getenv('OWNSTACK_PLANNER_SERVICE_TOKEN','')
    if len(expected)<32:raise HTTPException(503,'Planner service identity is not configured')
    if not x_ownstack_planner_key or not hmac.compare_digest(expected.encode(),x_ownstack_planner_key.encode()):
        raise HTTPException(401,'Planner service identity required')

@app.post('/plan')
def plan(command:Command,_identity=Depends(service_identity)):
    if runtime is None:raise HTTPException(503,'Checkpoint is not loaded')
    if not lock.acquire(blocking=False):raise HTTPException(429,'One local generation is already running')
    try:
        return inference_thread.submit(generate_plan,command).result()
    finally:lock.release()

def generate_plan(command):
        # Model initialization and execution share one GPU-owning thread. Web
        # request threads cannot move MLX streams across thread boundaries.
        torch,tokenizer,model,device,system,artifact=runtime
        if torch=='mlx':
            from mlx_lm import generate
            from mlx_lm.sample_utils import make_sampler
            prompt=tokenizer.apply_chat_template([{'role':'system','content':system},{'role':'user','content':command.text}],add_generation_prompt=True,enable_thinking=False,tokenize=False)
            if len(tokenizer.encode(prompt))>1536:raise HTTPException(422,'Command exceeds token limit')
            begin=time.perf_counter();output=generate(model,tokenizer,prompt=prompt,max_tokens=96,sampler=make_sampler(temp=0),verbose=False)
            import mlx.core as mx
            mx.clear_cache()
            return dict(output=output.strip(),artifact=artifact,latency_ms=round((time.perf_counter()-begin)*1000,2))
        encoded=tokenizer.apply_chat_template([{'role':'system','content':system},{'role':'user','content':command.text}],add_generation_prompt=True,enable_thinking=False,return_tensors='pt',return_dict=True).to(device)
        if encoded['input_ids'].shape[-1]>1536:raise HTTPException(422,'Command exceeds token limit')
        begin=time.perf_counter()
        with torch.inference_mode():result=model.generate(**encoded,max_new_tokens=96,max_time=45,do_sample=False,pad_token_id=tokenizer.eos_token_id)
        return dict(output=tokenizer.decode(result[0,encoded['input_ids'].shape[-1]:],skip_special_tokens=True).strip(),artifact=artifact,latency_ms=round((time.perf_counter()-begin)*1000,2))

if __name__=='__main__':
    import uvicorn
    runtime=inference_thread.submit(load).result()
    port=int(os.getenv('OWNSTACK_PLANNER_PORT','8811'))
    if not 1024<=port<=65535:raise RuntimeError('Use an unprivileged loopback port')
    uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning')
