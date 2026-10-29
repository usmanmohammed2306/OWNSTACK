"""Wire-protocol, scope and syntax boundaries; no model source executes here."""
import json
import pytest
from ownstack.source_proposals import replacement,repository_patch,model_sources


def test_line_data_preserves_python_escapes_blank_lines_unicode_and_indentation(tmp_path):
    marker=tmp_path/'never-execute'
    lines=[f'open({str(marker)!r}, "w").write("forbidden at parse time")','',
        'def render():','    return "café (Atlas)\\n"']
    source=replacement(json.dumps({'lines':lines}))
    assert source=='\n'.join(lines)+'\n' and not marker.exists()


@pytest.mark.parametrize('body',[
    {'replacement':'pass\\n'}, {'lines':'pass'}, {'lines':[]}, {'lines':['pass\npass']},
    {'lines':['pass\r']}, {'lines':['pass\0']}, {'lines':[1]}, {'lines':['pass'],'command':'deploy'},
    {'lines':[' '*2049]}, {'lines':['pass']*257},
])
def test_invalid_source_protocol_has_no_guessing_or_fallback(body):
    with pytest.raises(ValueError):replacement(json.dumps(body))


@pytest.mark.parametrize('lines',[
    ['def broken(:'], ['def f():','return 1'], ['def f():\\n    return 1'],
])
def test_new_protocol_still_rejects_invalid_python(lines):
    with pytest.raises(ValueError,match='MODEL_SOURCE_SYNTAX_INVALID'):replacement(json.dumps({'lines':lines}))


def test_server_binds_entire_exact_old_file_instead_of_model_supplied_anchors():
    original='def visible(actor):\n    return True\n'
    patch=repository_patch(json.dumps({'files':[{'path':'policy.py','lines':['def visible(actor):','    return actor.assigned']}]}),{'policy.py':original})
    assert patch['edits']==[{'path':'policy.py','old':original,'new':'def visible(actor):\n    return actor.assigned\n'}]


@pytest.mark.parametrize('path',['../policy.py','/policy.py','auth.py','policy.js','folder\\policy.py','./policy.py'])
def test_file_capability_cannot_expand(path):
    with pytest.raises(ValueError,match='MODEL_SOURCE_SCOPE_INVALID'):
        repository_patch(json.dumps({'files':[{'path':path,'lines':['pass']}]}),{'policy.py':'x=1\n'})


def test_duplicate_files_old_anchor_commands_and_noop_are_rejected():
    item={'path':'policy.py','lines':['pass']}
    for files in [[item,item],[{**item,'old':'invented'}]]:
        with pytest.raises(ValueError):repository_patch(json.dumps({'files':files}),{'policy.py':'x=1\n'})
    with pytest.raises(ValueError,match='MODEL_SOURCE_NO_CHANGE'):
        repository_patch(json.dumps({'files':[item]}),{'policy.py':'pass\n'})


def test_input_line_representation_preserves_source_identity_and_terminal_state():
    value='def f():\n    return "\\n"\n'
    before=model_sources({'policy.py':value})[0]
    assert before['lines']==['def f():','    return "\\n"'] and before['ends_with_newline']
    assert before['sha256']!=model_sources({'policy.py':value[:-1]})[0]['sha256']


def test_utf8_byte_limit_applies_after_line_rendering():
    with pytest.raises(ValueError):replacement(json.dumps({'lines':['#'+'é'*1000]*8}))
