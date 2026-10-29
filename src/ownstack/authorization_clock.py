"""Opt-in nondecreasing authorization time for a single database authority.

This is a fail-closed skew detector, not a trusted-time service or multi-region
consensus. It cannot recover real time from a compromised clock and database.
"""
from datetime import timedelta
import os
import threading
import time
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from ownstack.models import RuntimePulse
from ownstack.policy import aware

_anchor=None
_lock=threading.Lock()
TOLERANCE_SECONDS=2

def authorization_time(db,at):
    global _anchor
    at=aware(at)
    if os.getenv('OWNSTACK_ENFORCE_AUTH_CLOCK','false').lower()!='true':return at
    monotonic=time.monotonic()
    with _lock:
        if _anchor is None:_anchor=(at,monotonic)
        else:
            wall_elapsed=(at-_anchor[0]).total_seconds()
            if abs(wall_elapsed-(monotonic-_anchor[1]))>TOLERANCE_SECONDS:
                raise HTTPException(503,'Authorization clock changed unexpectedly. Access is paused pending operator review.')
    insert=pg_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
    db.execute(insert(RuntimePulse).values(component='authorization-clock',touched_at=at)
        .on_conflict_do_nothing(index_elements=['component']))
    row=db.scalar(select(RuntimePulse).where(RuntimePulse.component=='authorization-clock').with_for_update())
    floor=aware(row.touched_at)
    if (floor-at).total_seconds()>TOLERANCE_SECONDS:
        raise HTTPException(503,'Authorization clock is behind its saved authority. Access is paused pending operator review.')
    # Small process skew clamps to the persisted maximum: it cannot resurrect a
    # grant that this authority already observed as expired. Never lower the row.
    if at>floor:row.touched_at=at
    return max(at,floor)
