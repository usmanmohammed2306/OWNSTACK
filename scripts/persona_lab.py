"""Create or serve persistent synthetic accounts. Credentials never go to stdout."""
import argparse
import json
from pathlib import Path
from ownstack.persona_lab import ROOT,configure,initialize,gallery

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['init','serve','status'])
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8107)
    args=parser.parse_args();directory=args.directory.absolute()
    if not directory.resolve().is_relative_to((ROOT/'.private').resolve()):raise SystemExit('CLI laboratories belong under this project’s ignored .private directory')
    if directory.is_symlink():raise SystemExit('Do not use a symlink laboratory')
    if not 1024<=args.port<=65535:raise SystemExit('Use a nonprivileged loopback port')
    if args.action=='init':print(json.dumps(initialize(directory),indent=2));return
    manifest=configure(directory,args.port)
    if args.action=='status':print(json.dumps(manifest,indent=2));return
    from ownstack.api import app
    from fastapi.responses import HTMLResponse,Response
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    @app.get('/lab/personas')
    def personas():return json.loads((directory/'profiles.json').read_text())
    @app.get('/lab',response_class=HTMLResponse)
    def laboratory():return gallery(json.loads((directory/'profiles.json').read_text())['profiles'])
    @app.get('/lab/avatar/{persona_id}')
    def avatar(persona_id:str):
        import re
        from fastapi import HTTPException
        if not re.fullmatch(r'P(?:00[1-9]|0[1-9][0-9]|100)',persona_id):raise HTTPException(404,'Unknown synthetic identity')
        return Response((directory/'avatars'/(persona_id+'.svg')).read_text(),media_type='image/svg+xml',headers={'Cache-Control':'no-store'})
    if (ROOT/'web/dist/index.html').exists():app.mount('/',StaticFiles(directory=ROOT/'web/dist',html=True),name='local-persona-workspace')
    print(json.dumps({'url':f'http://127.0.0.1:{args.port}/','synthetic_accounts':manifest['accounts'],'provider_mode':'off','cap':0}),flush=True)
    uvicorn.run(app,host='127.0.0.1',port=args.port,access_log=False)

if __name__=='__main__':main()
