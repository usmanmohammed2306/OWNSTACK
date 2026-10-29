"""Preserve supported response bindings during a visibility-policy repair.

This conservative syntax contract catches accidental output reconstruction. It
does not prove program equivalence: independent execution and review still apply.
Unsupported source shapes keep their existing independent-check/manual path.
"""
import ast
from ownstack.policy import digest


def _handler(source):
    tree=ast.parse(source)
    handlers=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='read']
    return handlers[0] if len(handlers)==1 else None


def _mapping(node):
    if not isinstance(node,ast.Dict) or any(not isinstance(k,ast.Constant) or not isinstance(k.value,str) for k in node.keys):return None
    keys=[k.value for k in node.keys]
    return dict(zip(keys,node.values)) if len(keys)==len(set(keys)) else None


def _literal_or_input(node,argument):
    return isinstance(node,ast.Constant) or (isinstance(node,ast.Subscript)
        and isinstance(node.value,ast.Name) and node.value.id==argument
        and isinstance(node.slice,ast.Constant) and isinstance(node.slice.value,str))


def response_contract(source,policy):
    """Derive bindings from existing code, never from model-supplied claims."""
    fields=policy.get('visible_fields') if isinstance(policy,dict) else None
    if not fields:return None
    function=_handler(source)
    if function is None or len(function.args.args)!=1:return None
    argument=function.args.args[0].arg;bindings=None
    for node in ast.walk(function):
        if not isinstance(node,ast.Return):continue
        value=node.value
        if not (isinstance(value,ast.Tuple) and len(value.elts)==2
            and isinstance(value.elts[0],ast.Constant) and type(value.elts[0].value) is int and value.elts[0].value==200):continue
        mapping=_mapping(value.elts[1])
        if mapping is None:return None
        retained={k:v for k,v in mapping.items() if k in fields}
        if not retained or any(not _literal_or_input(v,argument) for v in retained.values()):return None
        current={k:{'ast':ast.dump(v,include_attributes=False),'source':ast.get_source_segment(source,v)} for k,v in retained.items()}
        if bindings is not None and current!=bindings:return None
        bindings=current
    if not bindings:return None
    contract={'version':1,'function':'read','preserved_fields':bindings,'approved_output_fields':sorted(fields)}
    return {**contract,'sha256':digest(contract)}


def validate_response_preservation(patch,context):
    """Reject changed bindings, without projecting or rewriting model output."""
    contracts={}
    for edit in patch['edits']:
        original=context['editable_files'][edit['path']]
        contract=response_contract(original,context.get('approved_policy'))
        if contract is None:continue
        contracts[edit['path']]=contract
        function=_handler(edit['new'])
        if function is None:raise ValueError('MODEL_RESPONSE_CONTRACT_INVALID')
        successes=0
        for node in ast.walk(function):
            if not isinstance(node,ast.Return):continue
            value=node.value
            if not isinstance(value,ast.Tuple) or len(value.elts)!=2:raise ValueError('MODEL_RESPONSE_CONTRACT_INVALID')
            status,body=value.elts
            if isinstance(status,ast.Constant) and type(status.value) is int and status.value!=200:continue
            # Dynamic denied-status expressions with an empty body are handled by
            # the independent oracle. They grant no preserved output mapping.
            if not isinstance(status,ast.Constant) and isinstance(body,ast.Dict) and not body.keys:continue
            mapping=_mapping(body)
            if mapping is None or sorted(mapping)!=contract['approved_output_fields']:raise ValueError('MODEL_RESPONSE_CONTRACT_INVALID')
            for field,binding in contract['preserved_fields'].items():
                if ast.dump(mapping[field],include_attributes=False)!=binding['ast']:raise ValueError('MODEL_RESPONSE_CONTRACT_INVALID')
            successes+=1
        if not successes:raise ValueError('MODEL_RESPONSE_CONTRACT_INVALID')
    return contracts
