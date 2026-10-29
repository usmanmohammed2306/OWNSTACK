"""Merge the verified LoRA, then derive a local eight-bit Apple checkpoint.

No hub upload and no replacement pretrained model. Evaluation of the derived
weights is required before enabling this backend in the application.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from serve_planner import load

def convert(destination:Path):
    if destination.exists():raise ValueError('Preserve previous conversion; choose a new destination')
    destination.mkdir(parents=True,mode=0o700)
    torch,tokenizer,model,device,system,artifact=load()
    merged=destination/'merged'
    model.to('cpu');model=model.merge_and_unload();model.save_pretrained(merged,safe_serialization=True);tokenizer.save_pretrained(merged)
    del model
    import gc
    gc.collect()
    if device=='mps':torch.mps.empty_cache()
    from mlx_lm.convert import convert as mlx_convert
    mlx_convert(str(merged),mlx_path=str(destination/'model'),quantize=True,q_bits=8,dtype='float16',trust_remote_code=False)
    files={str(p.relative_to(destination)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((destination/'model').rglob('*')) if p.is_file()}
    metadata={'schema':1,'source_manifest_sha256':artifact,'quantization_bits':8,'system':system,'files':files,'requires_heldout_evaluation':True}
    (destination/'conversion.json').write_text(json.dumps(metadata,indent=2))
    print(json.dumps({'conversion_sha256':hashlib.sha256((destination/'conversion.json').read_bytes()).hexdigest(),'files':len(files),'source_manifest_sha256':artifact}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination',type=Path);args=parser.parse_args();convert(args.destination)
