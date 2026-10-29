"""Owned sample customer app. This is a fixture, not an external buyer."""
def read(data):
    if data['actor_tenant_id']!=data['resource_tenant_id']:return 404,{}
    if data['actor_role']=='contractor':
        if not data['assigned']:return 403,{}
        return 200,{'id':data['resource_id'],'title':'Workspace document'}
    if data['actor_role'] in {'member','manager','engineer','admin'}:
        return 200,{'id':data['resource_id'],'title':'Workspace document','internal_notes':'Fixture notes'}
    return 403,{}
