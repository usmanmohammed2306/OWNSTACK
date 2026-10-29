"""Line-oriented Python proposals with server-owned source anchors.

The wire protocol separates source lines structurally instead of asking a model
to embed a whole program in one escaped JSON string. Rendering is specified LF,
never guessed unescaping. Parsing checks syntax without executing any statement.
Independent checks and human review still decide behavior and release readiness.
"""
import ast
import json
from pathlib import PurePosixPath
from pydantic import BaseModel,ConfigDict,Field,ValidationError,field_validator
from ownstack.model_contracts import strict_json

PROTOCOL='python-source-lines-v1'


class PythonLines(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    lines:list[str]=Field(min_length=1,max_length=256)

    @field_validator('lines')
    @classmethod
    def individual_lines(cls,value):
        if any(any(c in line for c in ('\n','\r','\0')) or len(line.encode('utf-8'))>2048 for line in value):
            raise ValueError('One bounded physical source line per element')
        return value

    def source(self,*,limit=12000,path='candidate.py'):
        source='\n'.join(self.lines)+'\n'
        if len(source.encode('utf-8'))>limit:raise ValueError('MODEL_SOURCE_PROTOCOL_INVALID')
        try:ast.parse(source,filename=path)
        except (SyntaxError,ValueError,RecursionError):raise ValueError('MODEL_SOURCE_SYNTAX_INVALID') from None
        return source


class FileLines(PythonLines):
    path:str=Field(min_length=1,max_length=240)


class SourceFiles(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid')
    files:list[FileLines]=Field(min_length=1,max_length=4)


def replacement(raw):
    try:value=PythonLines.model_validate(strict_json(raw,limit=64000))
    except (ValidationError,ValueError):raise ValueError('MODEL_SOURCE_PROTOCOL_INVALID') from None
    return value.source()


def repository_patch(raw,editable):
    """The model selects allowed files; only the server supplies exact old text."""
    try:value=SourceFiles.model_validate(strict_json(raw,limit=100000))
    except (ValidationError,ValueError):raise ValueError('MODEL_SOURCE_PROTOCOL_INVALID') from None
    paths=[file.path for file in value.files]
    if len(paths)!=len(set(paths)):raise ValueError('MODEL_SOURCE_PROTOCOL_INVALID')
    edits=[]
    for file in value.files:
        path=PurePosixPath(file.path)
        if (file.path not in editable or not file.path.endswith('.py') or path.is_absolute()
                or any(p in {'..','.'} for p in file.path.split('/')) or '\\' in file.path):
            raise ValueError('MODEL_SOURCE_SCOPE_INVALID')
        original=editable[file.path]
        if not isinstance(original,str) or not original or len(original.encode())>12000:
            raise ValueError('MODEL_SOURCE_SCOPE_INVALID')
        source=file.source(limit=20000,path=file.path)
        if source==original:raise ValueError('MODEL_SOURCE_NO_CHANGE')
        edits.append({'path':file.path,'old':original,'new':source})
    if len(json.dumps({'edits':edits}).encode())>64000:raise ValueError('MODEL_SOURCE_PROTOCOL_INVALID')
    return {'edits':edits}


def model_sources(editable):
    """Represent source faithfully as line data; no reference solution is added."""
    from hashlib import sha256
    if not isinstance(editable,dict) or not 1<=len(editable)<=4:raise ValueError('Bounded editable files required')
    result=[]
    for path,source in sorted(editable.items()):
        if not isinstance(source,str) or not source or len(source.encode())>12000:raise ValueError('Bounded source required')
        lines=source.split('\n')
        if source.endswith('\n'):lines.pop()
        result.append({'path':path,'sha256':sha256(source.encode()).hexdigest(),'lines':lines,'ends_with_newline':source.endswith('\n')})
    return result
