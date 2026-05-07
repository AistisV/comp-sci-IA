"""
database.py
-----------
Data access layer for the IB Physics Knowledge Navigator.

Manages the four-table SQLite schema:
  topics    – static syllabus nodes (seeded once from JSON)
  edges     – directed prerequisite links with composite PK (seeded once)
  questions – MCQ bank per topic (seeded once)
  progress  – per-topic status, updated at runtime

All external state flows through this module so the rest of the
application never constructs raw SQL.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH  = Path(__file__).parent / "physics_tutor.db"
JSON_PATH = Path(__file__).parent / "nodes.json"


# ── Connection helper ──────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    """Return a connection with foreign-key enforcement and row factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Schema initialisation ──────────────────────────────────────────────────────

def init_db() -> None:
    """
    Create all four tables if they do not already exist.
    Safe to call on every startup – uses CREATE TABLE IF NOT EXISTS.
    """
    conn = _connect()
    conn.executescript("""
        -- Static node catalogue: one row per syllabus topic.
        CREATE TABLE IF NOT EXISTS topics (
            id   TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );

        -- Directed prerequisite edges.
        -- Composite primary key (from_topic_id, to_topic_id) is the
        -- genuine relational justification for using a relational DB here:
        -- it enforces uniqueness of each directed pair while modelling the
        -- many-to-many self-join on topics that a DAG requires.
        CREATE TABLE IF NOT EXISTS edges (
            from_topic_id TEXT NOT NULL
                REFERENCES topics(id) ON DELETE CASCADE,
            to_topic_id   TEXT NOT NULL
                REFERENCES topics(id) ON DELETE CASCADE,
            PRIMARY KEY (from_topic_id, to_topic_id)
        );

        -- Multiple-choice question bank, linked to topics.
        -- options stored as a JSON array so no extra join table is needed.
        CREATE TABLE IF NOT EXISTS questions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id      TEXT    NOT NULL REFERENCES topics(id),
            text          TEXT    NOT NULL,
            options       TEXT    NOT NULL,   -- JSON array of option strings
            correct_index INTEGER NOT NULL
        );

        -- Runtime progress: one row per topic, updated as the student works.
        -- status is one of: 'available' | 'passed' | 'failed' | 'locked'
        CREATE TABLE IF NOT EXISTS progress (
            topic_id      TEXT PRIMARY KEY REFERENCES topics(id),
            status        TEXT NOT NULL DEFAULT 'available',
            last_attempted TEXT           -- ISO-8601 timestamp, nullable
        );
    """)
    conn.commit()
    conn.close()


# ── First-run seeding ──────────────────────────────────────────────────────────

def is_seeded() -> bool:
    """Return True if the topics table already contains rows."""
    conn = _connect()
    count = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    conn.close()
    return count > 0


def seed_from_json(path: Path = JSON_PATH) -> None:
    """
    Ingest the JSON syllabus file into the three static tables.
    Called exactly once on first run; guarded by is_seeded() in main.py.

    JSON schema expected per node:
      { "id": str, "name": str, "parent_ids": [str],
        "questions": [{"text": str, "options": [str], "correct_index": int}] }
    """
    with open(path, "r", encoding="utf-8") as fh:
        nodes: list[dict] = json.load(fh)

    conn = _connect()
    cur  = conn.cursor()

    for node in nodes:
        topic_id = node["id"]

        # Insert topic (ignore if somehow already present)
        cur.execute(
            "INSERT OR IGNORE INTO topics (id, name) VALUES (?, ?)",
            (topic_id, node["name"])
        )

        # Insert directed edges: parent → this topic
        for parent_id in node.get("parent_ids", []):
            cur.execute(
                "INSERT OR IGNORE INTO edges (from_topic_id, to_topic_id) "
                "VALUES (?, ?)",
                (parent_id, topic_id)
            )

        # Insert questions; options serialised as JSON
        for q in node.get("questions", []):
            cur.execute(
                "INSERT INTO questions "
                "(topic_id, text, options, correct_index) VALUES (?, ?, ?, ?)",
                (topic_id, q["text"], json.dumps(q["options"]), q["correct_index"])
            )

        # Initialise progress row (available = no attempt yet)
        cur.execute(
            "INSERT OR IGNORE INTO progress (topic_id, status) VALUES (?, 'available')",
            (topic_id,)
        )

    conn.commit()
    conn.close()


# ── Read helpers ───────────────────────────────────────────────────────────────

def get_all_topics() -> list[dict]:
    """Return list of {id, name} dicts for every topic."""
    conn = _connect()
    rows = conn.execute("SELECT id, name FROM topics").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_edges() -> list[tuple[str, str]]:
    """Return list of (from_topic_id, to_topic_id) tuples."""
    conn = _connect()
    rows = conn.execute(
        "SELECT from_topic_id, to_topic_id FROM edges"
    ).fetchall()
    conn.close()
    return [(r["from_topic_id"], r["to_topic_id"]) for r in rows]


def get_questions_for_topic(topic_id: str) -> list[dict]:
    """
    Return all questions for a topic as a list of dicts:
      {id, text, options: list[str], correct_index: int}
    """
    conn = _connect()
    rows = conn.execute(
        "SELECT id, text, options, correct_index "
        "FROM questions WHERE topic_id = ?",
        (topic_id,)
    ).fetchall()
    conn.close()
    return [
        {
            "id":            r["id"],
            "text":          r["text"],
            "options":       json.loads(r["options"]),
            "correct_index": r["correct_index"],
        }
        for r in rows
    ]


def get_all_progress() -> dict[str, dict]:
    """
    Return a dict mapping topic_id → {status, last_attempted}
    for every topic currently in the progress table.
    """
    conn = _connect()
    rows = conn.execute(
        "SELECT topic_id, status, last_attempted FROM progress"
    ).fetchall()
    conn.close()
    return {r["topic_id"]: dict(r) for r in rows}


# ── Write helpers ──────────────────────────────────────────────────────────────

def set_status(topic_id: str, status: str) -> None:
    """
    Update the status for a single topic and stamp last_attempted.
    Valid statuses: 'available', 'passed', 'failed', 'locked'.
    """
    conn = _connect()
    conn.execute(
        "UPDATE progress SET status = ?, last_attempted = ? WHERE topic_id = ?",
        (status, datetime.now().isoformat(timespec="seconds"), topic_id)
    )
    conn.commit()
    conn.close()


def reset_all_progress() -> None:
    """Revert every topic to 'available' and clear timestamps."""
    conn = _connect()
    conn.execute(
        "UPDATE progress SET status = 'available', last_attempted = NULL"
    )
    conn.commit()
    conn.close()
