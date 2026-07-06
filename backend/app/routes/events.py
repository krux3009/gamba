"""The settlement + board feed.

Field names are engine-compatible on purpose: the client engine (a port of
code proven on pitchside) settles on {id, status, home_goals_90, away_goals_90,
home_id, away_id, kickoff_utc}, so this route serves those aliases rather than
making every consumer learn the events-table names. For league soccer the
final score IS the 90-minute score (no extra time).
"""
from fastapi import APIRouter

from .. import db

router = APIRouter()

EVENTS_SQL = """
  SELECT id, sport, competition, home_name, away_name,
         home_ext_id AS home_id, away_ext_id AS away_id,
         kickoff_utc, status,
         home_score AS home_goals_90, away_score AS away_goals_90
    FROM events
   ORDER BY kickoff_utc
"""


@router.get("/api/events")
def events():
    conn = db.connect()
    try:
        # the whole table, no window: a device unopened for weeks must still
        # find the events its open bets reference, or they'd never settle.
        # Two league seasons ≈ 760 rows — pagination is a problem for another
        # order of magnitude.
        return conn.execute(EVENTS_SQL).fetchall()
    finally:
        conn.close()
