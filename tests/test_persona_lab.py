"""Synthetic profile integrity and private-fixture boundaries, not business proof."""
import csv
import json
from pathlib import Path
import pytest
from sqlalchemy import func,select,text
from sqlalchemy.orm import Session
from ownstack.persona_lab import PROFILES,audit_profiles,avatar_svg,configure,initialize,load_profiles,gallery


def changed_profiles(tmp_path,change):
    rows=load_profiles();change(rows);path=tmp_path/'profiles.tsv'
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter='\t');w.writeheader();w.writerows(rows)
    return path


def test_hundred_profiles_have_distinct_declared_needs_but_no_false_similarity_certificate():
    rows=load_profiles();audit=audit_profiles(rows)
    assert len(rows)==audit['unique_needs']==audit['unique_constraints']==100
    assert not audit['zero_similarity_guarantee'] and not audit['independent_semantic_review']
    assert audit['closest_lexical_pairs'][0]['jaccard']>0
    assert len({avatar_svg(r) for r in rows})==100
    rendered=gallery(rows)
    assert 'Passwords' in rendered and '100,000' in rendered and 'Business outcomes verified' in rendered
    assert 'zero similarity is not claimed' in rendered


@pytest.mark.parametrize('field',['name','occupation','need','constraint','success'])
def test_cosmetic_renaming_cannot_hide_exact_duplicate_profile_dimensions(tmp_path,field):
    path=changed_profiles(tmp_path,lambda rows:rows[1].update({field:rows[0][field]}))
    with pytest.raises(ValueError,match='Duplicate'):load_profiles(path)


def test_invalid_profile_count_and_control_characters_are_rejected(tmp_path):
    path=changed_profiles(tmp_path,lambda rows:rows.pop())
    with pytest.raises(ValueError,match='hundred'):load_profiles(path)
    path=changed_profiles(tmp_path,lambda rows:rows[0].update(need='bad\x00input'))
    with pytest.raises(ValueError,match='Control'):load_profiles(path)


def test_initialization_is_private_persistent_and_refuses_to_overwrite_existing_accounts(tmp_path,monkeypatch):
    # Hash transport is synthetic only for this filesystem/unit check. The actual
    # saved account experiment exercises all hundred real password hashes.
    monkeypatch.setattr('ownstack.auth.password_hash',lambda password:'unit-placeholder-not-a-valid-login-hash')
    directory=tmp_path/'lab';result=initialize(directory)
    assert result['accounts']==100 and result['provider_calls_allowed']==0
    assert not result['credentials_printed'] and result['business_journeys_completed']==0
    secrets_before=(directory/'accounts.json').read_bytes()
    accounts=json.loads(secrets_before)
    assert len({r['password'] for r in accounts.values()})==100
    assert all(len(r['password'])>=32 for r in accounts.values())
    for name in ['accounts.json','secrets.json','lab.sqlite','lab.json']:
        assert (directory/name).stat().st_mode&0o077==0
    from ownstack.db import make_engine
    from ownstack.models import InferenceBudget,Tenant,User
    engine=make_engine('sqlite:///'+str(directory/'lab.sqlite'))
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(User))==100
        assert db.scalar(select(func.count()).select_from(Tenant).where(Tenant.ai_enabled.is_(True)))==0
        assert db.get(InferenceBudget,'global').reserved_calls==0
        assert db.execute(text('select version_num from alembic_version')).scalar_one()=='e28f10d3a603'
    engine.dispose()
    with pytest.raises(FileExistsError):initialize(directory)
    assert (directory/'accounts.json').read_bytes()==secrets_before
    link=tmp_path/'link';link.symlink_to(directory,target_is_directory=True)
    with pytest.raises(ValueError,match='symlink'):configure(link)
    (directory/'accounts.json').chmod(0o644)
    with pytest.raises(ValueError,match='private permissions'):configure(directory)


def test_unsafe_html_profile_text_is_escaped_not_executed():
    row={**load_profiles()[0],'name':'<script>alert(1)</script>','need':'<img src=x onerror=alert(2)>'}
    assert '<script>alert(1)</script>' not in avatar_svg(row)
    assert '<img src=x onerror=' not in gallery([row])


def test_unknown_directory_cannot_select_the_active_project_database(tmp_path):
    with pytest.raises(ValueError,match='Missing'):configure(tmp_path)
