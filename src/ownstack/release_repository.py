"""Explicit, bounded source onboarding for an operator-reviewed HTTP adapter.

Only declared regular source files enter the container. No dependency install,
Git fetch, executable config, provider credentials or model-authored shell runs.
The adapter is untrusted code and must serve the reviewed protocol on port8765.
"""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import stat

from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from ownstack.model_contracts import strict_json

PROFILE='python-repository-http-v1'
MANIFEST='ownstack.release.json'
MAX_FILES=1024
MAX_FILE=4*1024*1024
MAX_TREE=32*1024*1024
FORBIDDEN={'.git','.env','.private','.venv','node_modules','__pycache__','.ssh','.aws','.azure','.codex'}


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def relative(value):
    if not isinstance(value,str) or not value or len(value)>240:raise ValueError('Bounded relative source path required')
    parts=PurePosixPath(value).parts
    if (PurePosixPath(value).is_absolute() or value!=PurePosixPath(value).as_posix() or '\\' in value
        or any(ord(c)<32 for c in value) or any(p.casefold() in {'.','..',*FORBIDDEN} for p in parts)
        or any(p.casefold().startswith('.env') for p in parts) or value==MANIFEST
        or Path(value).suffix.lower() in {'.db','.sqlite','.sqlite3','.pem','.key','.p12','.dump','.pyc'}):
        raise ValueError('Private, ambiguous or unsafe source path')
    return value


class RepositoryManifest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)
    version:int=Field(ge=1,le=1)
    name:str=Field(min_length=1,max_length=80,pattern=r'^[A-Za-z0-9][A-Za-z0-9 ._-]*$')
    profile:str=Field(pattern=r'^python-repository-http-v1$')
    entrypoint:str
    files:list[str]=Field(min_length=1,max_length=MAX_FILES)

    @field_validator('entrypoint')
    @classmethod
    def entry(cls,value):
        relative(value)
        if not value.endswith('.py'):raise ValueError('Python adapter entrypoint required')
        return value

    @field_validator('files')
    @classmethod
    def paths(cls,values):
        for value in values:relative(value)
        if len({v.casefold() for v in values})!=len(values):raise ValueError('Duplicate or case-ambiguous source paths')
        return sorted(values)

    @model_validator(mode='after')
    def included(self):
        if self.entrypoint not in self.files:raise ValueError('Entrypoint must be in the reviewed source inventory')
        return self


def regular(root,name,limit=MAX_FILE):
    path=root/name
    for parent in (path,*path.parents):
        if parent.is_symlink():raise ValueError('No symlink source or ancestor')
        if parent==root:break
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0<before.st_size<=limit:raise ValueError('Bounded nonempty regular source required')
        chunks=[];size=0
        while True:
            data=os.read(fd,min(65536,limit+1-size))
            if not data:break
            chunks.append(data);size+=len(data)
            if size>limit:raise ValueError('Source file exceeds bound')
        after=os.fstat(fd)
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or size!=before.st_size:
            raise ValueError('Source changed while snapshotting')
        raw=b''.join(chunks);raw.decode('utf-8');return raw
    finally:os.close(fd)


def load(root):
    root=Path(root).absolute()
    if not root.is_dir() or any(p.is_symlink() for p in (root,*root.parents)):raise ValueError('Explicit nonsymlink repository directory required')
    config=RepositoryManifest.model_validate(strict_json(regular(root,MANIFEST,262144).decode(),limit=262144))
    files={};total=0
    for name in config.files:
        raw=regular(root,name);total+=len(raw)
        if total>MAX_TREE:raise ValueError('Reviewed source tree exceeds32 MiB')
        files[name]=raw
    snapshot={'profile':PROFILE,'config':config.model_dump(),'files':{n:hashlib.sha256(raw).hexdigest() for n,raw in files.items()}}
    snapshot['sha256']=digest(snapshot)
    return snapshot,files


def validate_snapshot(snapshot):
    if not isinstance(snapshot,dict) or set(snapshot)!={'profile','config','files','sha256'} or snapshot['profile']!=PROFILE:
        raise ValueError('Unsupported source snapshot')
    config=RepositoryManifest.model_validate(snapshot['config'])
    if config.model_dump()!=snapshot['config'] or set(snapshot['files'])!=set(config.files):raise ValueError('Source inventory differs from manifest')
    if any(not isinstance(h,str) or not re.fullmatch('[a-f0-9]{64}',h) for h in snapshot['files'].values()):raise ValueError('Source digests required')
    if snapshot['sha256']!=digest({k:v for k,v in snapshot.items() if k!='sha256'}):raise ValueError('Source snapshot digest mismatch')
    return config


def initialize(root,*,name,entrypoint,include):
    root=Path(root).absolute();paths=[]
    if not root.is_dir() or any(p.is_symlink() for p in (root,*root.parents)):raise ValueError('Explicit nonsymlink repository directory required')
    for value in include:
        relative(value);path=root/value
        if path.is_symlink():raise ValueError('Symlink include forbidden')
        if path.is_dir():
            for directory,dirs,files in os.walk(path,followlinks=False):
                for part in dirs:
                    if (Path(directory)/part).is_symlink():raise ValueError('Symlink include forbidden')
                dirs[:]=sorted(p for p in dirs if p.casefold() not in FORBIDDEN)
                for part in sorted(files):
                    nested=Path(directory)/part
                    if nested.is_symlink():raise ValueError('Symlink include forbidden')
                    if nested.suffix=='.pyc':continue
                    paths.append(relative(nested.relative_to(root).as_posix()))
                    if len(paths)>MAX_FILES:raise ValueError('Too many included files')
        elif path.is_file():paths.append(value)
        else:raise ValueError('Included source path is missing')
    manifest=RepositoryManifest(version=1,name=name,profile=PROFILE,entrypoint=entrypoint,files=sorted(set(paths)))
    total=0
    for path in manifest.files:
        total+=len(regular(root,path))
        if total>MAX_TREE:raise ValueError('Reviewed source tree exceeds32 MiB')
    target=root/MANIFEST
    with target.open('x') as file:file.write(json.dumps(manifest.model_dump(),indent=2)+'\n')
    return load(root)[0]
