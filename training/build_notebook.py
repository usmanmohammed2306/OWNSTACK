"""Build a private-use training notebook and materialize the authored dataset.

Generation reads repository source only. It never reads .env, a database, a
credential file or customer data. Upload this notebook, not the project folder.
"""
import json
from pathlib import Path
from action_planner import dataset, canonical

def build():
    root=Path(__file__).resolve().parent
    source=(root/'action_planner.py').read_text()
    cells=[{'cell_type':'markdown','metadata':{},'source':[
        '# OwnStack: train a bounded interaction planner\n',
        'Use a free T4 GPU runtime. Do not upgrade or mount private Drive data.\n',
        'This notebook contains authored synthetic text only. It performs supervised LoRA fine-tuning, not reinforcement learning.\n',
        'Plans cannot approve, run shell commands or deploy. Base and fine-tuned outputs are retained for held-out comparison.\n',
        'Free availability varies. Stop if a paid runtime is required. Disconnect after exporting.\n']},
        {'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],
         'source':('%pip -q install '+ ' '.join((root/'requirements.txt').read_text().splitlines())+'\nimport torch\nassert torch.cuda.is_available(), "Select a free T4, or stop. No paid fallback."\n').splitlines(keepends=True)},
        {'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],
         'source':('%%writefile /content/ownstack_action_planner.py\n'+source).splitlines(keepends=True)},
        {'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],
         'source':['!python /content/ownstack_action_planner.py --output /content/ownstack-planner-run --steps 120\n']},
        {'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],
         'source':['from google.colab import files\n','files.download("/content/ownstack-planner-run.zip")\n']}]
    for index,cell in enumerate(cells):cell['id']=f'ownstack-step-{index+1}'
    notebook={'nbformat':4,'nbformat_minor':5,'metadata':{'accelerator':'GPU','kernelspec':{'display_name':'Python 3','name':'python3'}},'cells':cells}
    (root/'OwnStack_Planner.ipynb').write_text(json.dumps(notebook,indent=2))
    (root/'commands.jsonl').write_text('\n'.join(canonical(r) for r in dataset())+'\n')
    print(json.dumps({'notebook':'training/OwnStack_Planner.ipynb','synthetic_rows':len(dataset())}))

if __name__=='__main__':build()
