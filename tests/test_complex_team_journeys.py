"""Connected control journeys. Real clock/container runs are saved separately."""
from uuid import uuid4
from sqlalchemy import select
from conftest import login
from ownstack.models import TeamMembership,User,Variation
from ownstack.team_scope import add_general_member
from test_governance import setup,approve,read


def test_pending_dual_review_loses_the_departed_team_reviewer(client,fixture_db):
    _,proposal,admin=setup(client,fixture_db)
    first=approve(client,admin,proposal)
    assert first.json()['status']=='awaiting_second_approval'
    with fixture_db() as db:
        team=db.scalar(select(TeamMembership).where(TeamMembership.user_id=='atlas-admin')).team_id
    second=login(client,'atlas-admin-two')
    changed=client.put(f'/v1/teams/{team}/members/atlas-admin',headers=second,
        json={'role':'manager','enabled':False,'expected_revision':1})
    assert changed.status_code==200
    result=approve(client,second,proposal)
    assert result.status_code==200
    assert result.json()['status']=='awaiting_second_approval'
    assert result.json()['approvals']==1
    assert read(client).status_code==403


def test_only_the_reviews_selected_at_activation_can_sustain_quorum(client,fixture_db):
    with fixture_db() as db:
        template=db.get(User,'atlas-admin')
        person=User(id='atlas-admin-three',tenant_id='atlas',role='admin',enabled=True,
            password_hash=template.password_hash,token_version=1)
        db.add(person);db.flush();add_general_member(db,person);db.commit()
    _,proposal,admin=setup(client,fixture_db)
    assert approve(client,admin,proposal).json()['status']=='awaiting_second_approval'
    second=login(client,'atlas-admin-two');third=login(client,'atlas-admin-three')
    with fixture_db() as db:team=db.scalar(select(TeamMembership).where(TeamMembership.user_id=='atlas-admin')).team_id
    assert client.put(f'/v1/teams/{team}/members/atlas-admin',headers=second,
        json={'role':'manager','enabled':False,'expected_revision':1}).status_code==200
    assert approve(client,second,proposal).json()['status']=='awaiting_second_approval'
    activated=approve(client,third,proposal)
    assert activated.status_code==200 and activated.json()['status']=='active'
    assert read(client).status_code==200
    # Post-activation team transfer does not silently revoke a captured grant.
    assert client.put(f'/v1/teams/{team}/members/atlas-admin-three',headers=second,
        json={'role':'manager','enabled':False,'expected_revision':1}).status_code==200
    assert read(client).status_code==200
    assert client.post('/v1/members/me/revoke-sessions',headers=third).status_code==200
    # The departed first review must not replace the revoked selected reviewer.
    assert read(client).status_code==403
    assert client.get('/v1/variations',headers=second).json()[0]['state']=='suspended'
