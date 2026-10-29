"""Private engineering context is not customer-visible request text."""
from ownstack.workspace_models import RequestWorkspace


def engineering_prompt(db,request):
    row=db.get(RequestWorkspace,request.id)
    return row.effective_text if row and row.effective_text is not None else request.text
