"""Human-authored synthetic application, independent of OwnStack's oracle."""
from datetime import datetime


def read(data):
    if data['actor_tenant_id'] != data['resource_tenant_id']:
        return 404, {}
    if data['actor_role'] == 'anonymous':
        return 403, {}
    assigned_role = data['assigned'] and data['actor_role'] in ('engineer', 'manager')
    grant = False
    if data.get('grant_starts_at') and not data.get('grant_revoked', False):
        at = datetime.fromisoformat(data['at'])
        grant = datetime.fromisoformat(data['grant_starts_at']) <= at < datetime.fromisoformat(data['grant_expires_at'])
    if assigned_role or grant:
        return 200, {'id': data['resource_id'], 'title': 'Synthetic project brief'}
    return 403, {}
