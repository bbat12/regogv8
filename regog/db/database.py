"""
REGOG Database — SQLite connection, initialization, and helpers.
"""

import sqlite3
import json
import uuid
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from config import DB_PATH


# Fields stored as JSON strings in SQLite — auto-serialized on write, auto-deserialized on read
_JSON_FIELDS = {
    "brain_red_flags",
    "brain_green_flags",
    "price_history",
    "permit_flags",
    "comp_listings",
}



def _serialize_value(key: str, value: Any) -> Any:
    """Serialize value for DB storage. Lists/dicts become JSON strings."""
    if key in _JSON_FIELDS and isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


def _deserialize_row(row: sqlite3.Row) -> dict:
    """Deserialize a DB row, parsing JSON fields back to Python objects."""
    d = dict(row)
    for key in _JSON_FIELDS:
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def get_db_path() -> str:
    """Return the database file path."""
    return DB_PATH


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Get a SQLite connection with row factory enabled."""
    conn = sqlite3.connect(db_path or get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize the database from schema.sql, with migrations."""
    conn = get_connection(db_path)
    schema_path = Path(__file__).parent / "schema.sql"
    with open(schema_path) as f:
        conn.executescript(f.read())

    # ── Migrations for existing databases ──────────────────────────────
    _run_migrations(conn)

    conn.commit()
    conn.close()
    print(f"✓ Database initialized at {db_path or get_db_path()}")


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Run any needed migrations on the existing database."""
    # Get existing columns
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(properties)").fetchall()
    }

    migrations = [
        ("estimated_value", "INTEGER", "ALTER TABLE properties ADD COLUMN estimated_value INTEGER"),
        ("county", "TEXT", "ALTER TABLE properties ADD COLUMN county TEXT"),
        ("flood_zone", "TEXT", "ALTER TABLE properties ADD COLUMN flood_zone TEXT"),
        ("property_url", "TEXT", "ALTER TABLE properties ADD COLUMN property_url TEXT"),
        ("style", "TEXT", "ALTER TABLE properties ADD COLUMN style TEXT"),
        ("comp_confidence", "TEXT", "ALTER TABLE properties ADD COLUMN comp_confidence TEXT"),
        ("data_confidence", "TEXT", "ALTER TABLE properties ADD COLUMN data_confidence TEXT"),
        ("comp_listings", "TEXT", "ALTER TABLE properties ADD COLUMN comp_listings TEXT"),
        ("comp_radius_used", "REAL", "ALTER TABLE properties ADD COLUMN comp_radius_used REAL"),
        ("comp_tier_used", "INTEGER", "ALTER TABLE properties ADD COLUMN comp_tier_used INTEGER"),
        ("comp_category", "TEXT", "ALTER TABLE properties ADD COLUMN comp_category TEXT"),
        ("comp_density", "TEXT", "ALTER TABLE properties ADD COLUMN comp_density TEXT"),
        ("comp_lookback_used", "INTEGER", "ALTER TABLE properties ADD COLUMN comp_lookback_used INTEGER"),
        ("comp_confidence_label", "TEXT", "ALTER TABLE properties ADD COLUMN comp_confidence_label TEXT"),
        ("comp_staleness_penalty_applied", "INTEGER", "ALTER TABLE properties ADD COLUMN comp_staleness_penalty_applied INTEGER"),
    ]

    for col_name, col_type, sql in migrations:
        if col_name not in existing:
            try:
                conn.execute(sql)
                print(f"✓ Migration: added column '{col_name}' ({col_type})")
            except Exception as e:
                print(f"⚠ Migration: could not add '{col_name}': {e}")


def create_scan_session(conn: sqlite3.Connection, scan_type: str, search_params: dict) -> str:
    """Create a new scan session and return its ID."""
    session_id = str(uuid.uuid4())[:8]
    conn.execute(
        """INSERT INTO scan_sessions (id, started_at, scan_type, search_params)
           VALUES (?, ?, ?, ?)""",
        (session_id, datetime.utcnow().isoformat(), scan_type, json.dumps(search_params)),
    )
    conn.commit()
    return session_id


def complete_scan_session(conn: sqlite3.Connection, session_id: str, properties_found: int, hot_leads: int) -> None:
    """Mark a scan session as completed."""
    conn.execute(
        """UPDATE scan_sessions
           SET completed_at = ?, properties_found = ?, hot_leads_found = ?
           WHERE id = ?""",
        (datetime.utcnow().isoformat(), properties_found, hot_leads, session_id),
    )
    conn.commit()


def upsert_property(conn: sqlite3.Connection, prop: dict) -> bool:
    """Insert or update a property. Returns True if new, False if updated."""
    listing_id = prop.get("listing_id")
    if not listing_id:
        return False

    now = datetime.utcnow().isoformat()
    existing = conn.execute(
        "SELECT id, last_updated FROM properties WHERE listing_id = ?", (listing_id,)
    ).fetchone()

    if existing:
        # Update existing
        set_clause = ", ".join(f"{k} = ?" for k in prop.keys() if k != "listing_id")
        values = [_serialize_value(k, prop[k]) for k in prop.keys() if k != "listing_id"]
        conn.execute(
            f"UPDATE properties SET {set_clause}, last_updated = ? WHERE listing_id = ?",
            (*values, now, listing_id),
        )
        return False
    else:
        # Insert new
        prop["first_seen"] = now
        prop["last_updated"] = now
        serialized = {k: _serialize_value(k, v) for k, v in prop.items()}
        columns = ", ".join(serialized.keys())
        placeholders = ", ".join("?" for _ in serialized)
        conn.execute(
            f"INSERT INTO properties ({columns}) VALUES ({placeholders})",
            list(serialized.values()),
        )
        return True


def get_session_properties(conn: sqlite3.Connection, session_id: str) -> list[dict]:
    """Get all properties for a scan session, ordered by score descending."""
    rows = conn.execute(
        "SELECT * FROM properties WHERE scan_session_id = ? ORDER BY score_total DESC",
        (session_id,),
    ).fetchall()
    return [_deserialize_row(row) for row in rows]


def get_leads_by_tier(conn: sqlite3.Connection, tier: str, limit: int = 20) -> list[dict]:
    """Get top properties by tier."""
    rows = conn.execute(
        "SELECT * FROM properties WHERE lead_tier = ? ORDER BY score_total DESC LIMIT ?",
        (tier, limit),
    ).fetchall()
    return [_deserialize_row(row) for row in rows]


def search_properties(
    conn: sqlite3.Connection,
    scan_type: Optional[str] = None,
    tier: Optional[str] = None,
    score_min: Optional[float] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    limit: int = 50,
) -> list[dict]:
    """Search properties with optional filters."""
    query = "SELECT * FROM properties WHERE 1=1"
    params = []

    if scan_type:
        query += " AND scan_type = ?"
        params.append(scan_type)
    if tier:
        query += " AND lead_tier = ?"
        params.append(tier)
    if score_min is not None:
        query += " AND score_total >= ?"
        params.append(score_min)
    if city:
        query += " AND city LIKE ?"
        params.append(f"%{city}%")
    if state:
        query += " AND state = ?"
        params.append(state)
    if zip_code:
        query += " AND zip = ?"
        params.append(zip_code)
    if price_min is not None:
        query += " AND list_price >= ?"
        params.append(price_min)
    if price_max is not None:
        query += " AND list_price <= ?"
        params.append(price_max)

    query += " ORDER BY score_total DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [_deserialize_row(row) for row in rows]


def get_stats(conn: sqlite3.Connection) -> dict:
    """Get aggregate stats from the database."""
    total = conn.execute("SELECT COUNT(*) as c FROM properties").fetchone()["c"]
    hot = conn.execute("SELECT COUNT(*) as c FROM properties WHERE lead_tier = 'HOT'").fetchone()["c"]
    warm = conn.execute("SELECT COUNT(*) as c FROM properties WHERE lead_tier = 'WARM'").fetchone()["c"]
    sessions = conn.execute("SELECT COUNT(*) as c FROM scan_sessions").fetchone()["c"]

    avg_score = conn.execute("SELECT AVG(score_total) as avg FROM properties WHERE score_total IS NOT NULL").fetchone()["avg"]

    return {
        "total_properties": total,
        "hot_leads": hot,
        "warm_leads": warm,
        "scan_sessions": sessions,
        "avg_score": round(avg_score or 0, 1),
    }
