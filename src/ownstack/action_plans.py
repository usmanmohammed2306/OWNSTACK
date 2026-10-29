"""Validate learned UI plans independently of model prose or confidence.

There is deliberately no approval, shell, permission mutation or release action.
The output is a reviewable presentation/draft plan, not a capability contract.
"""
import json
import re
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Station = Literal['demo','journey','access','engineering','convergence']

class StrictAction(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Navigate(StrictAction):
    action: Literal['navigate']
    target: Station

class Theme(StrictAction):
    action: Literal['theme']
    target: Literal['ice','violet','mint']

class Move(StrictAction):
    action: Literal['move']
    target: Station
    x: float = Field(ge=-4, le=4, allow_inf_nan=False)
    z: float = Field(ge=-4, le=4, allow_inf_nan=False)

class Draft(StrictAction):
    action: Literal['draft']
    target: Literal['access','feature']

class Stop(StrictAction):
    action: Literal['clarify','refuse','reset']

Action = Annotated[Navigate | Theme | Move | Draft | Stop, Field(discriminator='action')]

class ActionPlan(StrictAction):
    actions: list[Action] = Field(min_length=1,max_length=4)

def validate_plan(raw: str, role: str) -> ActionPlan:
    if len(raw)>4096: raise ValueError('Plan is too large')
    # Reject duplicate keys; JSON last-key-wins can hide a different reviewed effect.
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value: raise ValueError('Duplicate JSON key')
            value[key]=item
        return value
    value=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite number')))
    plan=TypeAdapter(ActionPlan).validate_python(value)
    allowed={'admin':{'demo','journey','access','engineering','convergence'},
             'engineer':{'demo','journey','access','engineering','convergence'},
             'member':{'demo','journey','access'},'contractor':{'demo','journey'},
             'product_owner':{'demo','convergence'}}.get(role,{'demo'})
    for action in plan.actions:
        if isinstance(action,(Navigate,Move)) and action.target not in allowed:
            raise ValueError('That destination is unavailable for this role')
        if isinstance(action,Draft) and role not in {'admin','engineer','member'}:
            raise ValueError('This role cannot create requests')
    if any(isinstance(a,Stop) and a.action in {'refuse','clarify'} for a in plan.actions) and len(plan.actions)!=1:
        raise ValueError('A refusal or clarification cannot be combined with effects')
    if sum(isinstance(a,Draft) for a in plan.actions)>1:
        raise ValueError('One draft per plan')
    return plan


def validate_command_plan(raw: str, role: str, command: str) -> ActionPlan:
    """Ground visual mutations in explicit words independently of the model.

    Schema validity does not establish user intent. This conservative vocabulary
    check rejects ungrounded colors, directions and resets. It is not a general
    semantic verifier: the user still reviews the scene preview before Apply.
    Drafts still use the host-owned form and cannot submit or approve a request.
    """
    plan = validate_plan(raw, role)
    words = set(re.findall(r"[a-z]+", command.casefold()))
    colors = {"ice": {"ice", "arctic", "silver", "white"},
              "violet": {"violet", "purple", "lilac"},
              "mint": {"mint", "green", "emerald"}}
    labels = {"demo": {"workspace", "organization", "company"},
              "journey": {"request", "requests"}, "access": {"access", "permissions"},
              "engineering": {"code", "engineering"}, "convergence": {"patterns", "convergence"}}
    directions = {"left": (-3, 0), "right": (3, 0), "front": (0, 3), "back": (0, -3)}
    for action in plan.actions:
        if isinstance(action, Theme) and not words & colors[action.target]:
            raise ValueError("The proposed palette is not named in the command")
        if isinstance(action, Move):
            mentioned = {position for name, position in directions.items() if name in words}
            if (not words & labels[action.target] or len(mentioned) != 1
                    or (action.x, action.z) not in mentioned
                    or not words & {"move", "put", "place", "shift", "reposition", "slide", "arrange"}):
                raise ValueError("The proposed layout move is not explicit in the command")
        if isinstance(action, Stop) and action.action == "reset":
            if (not words & {"reset", "restore", "undo", "default", "defaults", "original", "factory", "clear"}
                    or not words & {"scene", "layout", "visual", "preferences", "arrangement", "objects"}):
                raise ValueError("Only an explicit visual-layout reset is supported")
    return plan


def resolve_command_plan(raw: str, role: str, command: str) -> tuple[ActionPlan, str]:
    """Resolve explicit single-navigation intent after the mandatory model call.

    This is a hybrid application boundary, not a repaired model or a new trained
    score. Never import benchmark labels here. Reject malformed/privileged output
    before considering a correction. Unknown or conflicting visual intent asks
    for clarification, rather than inventing a layout change.
    """
    original = validate_plan(raw, role)
    # Ambiguity handling may not downgrade an existing refusal to a clarification.
    if original.actions[0].action=='refuse':return original,'model'
    text = command.strip().casefold()
    labels = {'workspace':'demo','requests':'journey','access':'access','code':'engineering','patterns':'convergence'}
    explicit = re.match(r"^(?:please\s+)?(?:show(?:\s+me)?|open|display|inspect|bring\s+up|go\s+to)\s+(?:(?:the|my)\s+)?(workspace|requests|access|code|patterns)\b", text)
    additional = re.search(r"(?:[;,]|\b(?:and\s+then|and|then|also)\b)\s+(?:please\s+)?(?:open|show|move|reset|change|approve|deploy|execute|grant|revoke|disable)\b", text)
    negation = re.search(r"\b(?:do\s+not|don't|never|without|instead\s+of)\b", text)
    if explicit and not additional and not negation and original.actions[0].action!='refuse':
        result = validate_plan(json.dumps({'actions':[{'action':'navigate','target':labels[explicit[1]]}]}), role)
        return result, 'model' if result == original else 'explicit_navigation'
    if additional or (negation and any(isinstance(a,(Move,Theme)) or a.action=='reset' for a in original.actions)):
        return validate_plan('{"actions":[{"action":"clarify"}]}',role), 'ambiguous_command'
    try:
        return validate_command_plan(raw,role,command), 'model'
    except ValueError:
        return validate_plan('{"actions":[{"action":"clarify"}]}',role), 'intent_grounding'
