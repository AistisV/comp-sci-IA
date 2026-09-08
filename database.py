"""
database.py — Module 1: Data Management (DatabaseManager)

Implements the SQLite schema exactly as drawn in the ERD (Criterion C,
Figure 4): topics, edges, progress, questions, options. Topic and
Progress are kept as separate tables (per the IA's stated design
rationale) so that a future multi-user version only needs to add a
user_id column to `progress` rather than restructuring `topics`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from graph import Graph, Topic

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    topic_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    parent_id TEXT NOT NULL,
    child_id TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id),
    FOREIGN KEY (parent_id) REFERENCES topics(topic_id),
    FOREIGN KEY (child_id) REFERENCES topics(topic_id)
);

CREATE TABLE IF NOT EXISTS progress (
    topic_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);

CREATE TABLE IF NOT EXISTS questions (
    question_id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id TEXT NOT NULL,
    question_text TEXT NOT NULL,
    FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
);

CREATE TABLE IF NOT EXISTS options (
    option_id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    option_text TEXT NOT NULL,
    is_correct BOOLEAN NOT NULL,
    FOREIGN KEY (question_id) REFERENCES questions(question_id)
);
"""


class DatabaseManager:
    """Manages all CRUD operations for topics, edges, progress and quiz data."""

    def __init__(self, db_path: str = "physics_tutor.db"):
        self.db_path = db_path
        self.connection = sqlite3.connect(self.db_path)
        self.connection.execute("PRAGMA foreign_keys = ON;")

    # ------------------------------------------------------------------
    # SC1 / SC10: initialisation & seeding
    # ------------------------------------------------------------------

    def initialise_db(self) -> None:
        """Creates all tables if they do not already exist."""
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def is_seeded(self) -> bool:
        """True if the topics table already has data (skip re-seeding)."""
        cur = self.connection.execute("SELECT COUNT(*) FROM topics;")
        return cur.fetchone()[0] > 0

    def seed_from_json(self, file_path: str) -> None:
        """
        One-time transfer of the client-supplied JSON syllabus into the
        relational database: topics, edges, questions and options.
        Does nothing if the database has already been seeded, so the
        JSON can be re-provided without wiping student progress.
        """
        if self.is_seeded():
            return

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cur = self.connection.cursor()
        for topic in data:
            cur.execute(
                "INSERT OR IGNORE INTO topics (topic_id, name) VALUES (?, ?);",
                (topic["id"], topic["name"]),
            )
            cur.execute(
                "INSERT OR IGNORE INTO progress (topic_id, status) VALUES (?, ?);",
                (topic["id"], Topic.STATUS_UNTESTED),
            )
            for parent_id in topic.get("parent_ids", []):
                cur.execute(
                    "INSERT OR IGNORE INTO edges (parent_id, child_id) VALUES (?, ?);",
                    (parent_id, topic["id"]),
                )
            for q in topic.get("questions", []):
                cur.execute(
                    "INSERT INTO questions (topic_id, question_text) VALUES (?, ?);",
                    (topic["id"], q["text"]),
                )
                question_id = cur.lastrowid
                for i, option_text in enumerate(q["options"]):
                    cur.execute(
                        "INSERT INTO options (question_id, option_text, is_correct) "
                        "VALUES (?, ?, ?);",
                        (question_id, option_text, i == q["correct_index"]),
                    )
        self.connection.commit()

    def load_graph(self) -> Graph:
        """
        Builds and returns a fully populated Graph object from the
        database: topics (with their persisted status), then edges.
        """
        graph = Graph()
        cur = self.connection.execute(
            "SELECT t.topic_id, t.name, p.status "
            "FROM topics t JOIN progress p ON t.topic_id = p.topic_id;"
        )
        for topic_id, name, status in cur.fetchall():
            graph.add_topic(Topic(topic_id, name, status))

        cur = self.connection.execute("SELECT parent_id, child_id FROM edges;")
        for parent_id, child_id in cur.fetchall():
            graph.add_edge(parent_id, child_id)

        return graph

    # ------------------------------------------------------------------
    # SC10: progress persistence
    # ------------------------------------------------------------------

    def save_progress(self, topic_id: str, status: str) -> None:
        self.connection.execute(
            "UPDATE progress SET status = ? WHERE topic_id = ?;", (status, topic_id)
        )
        self.connection.commit()

    def save_progress_batch(self, topic_ids: list[str], status: str) -> None:
        """Single batch UPDATE for locking many nodes at once (Figure 10)."""
        if not topic_ids:
            return
        self.connection.executemany(
            "UPDATE progress SET status = ? WHERE topic_id = ?;",
            [(status, tid) for tid in topic_ids],
        )
        self.connection.commit()

    def load_progress(self) -> dict[str, str]:
        cur = self.connection.execute("SELECT topic_id, status FROM progress;")
        return dict(cur.fetchall())

    def reset_all_progress(self) -> None:
        """Resets every topic to 'Untested' (used by a UI reset action)."""
        self.connection.execute(
            "UPDATE progress SET status = ?;", (Topic.STATUS_UNTESTED,)
        )
        self.connection.commit()

    # ------------------------------------------------------------------
    # SC5: quiz question retrieval
    # ------------------------------------------------------------------

    def get_questions(self, topic_id: str) -> list[dict]:
        """
        Returns every question for a topic, each as:
            {"question_id": int, "text": str, "options": [str, ...],
             "correct_index": int}
        """
        questions = []
        cur = self.connection.execute(
            "SELECT question_id, question_text FROM questions WHERE topic_id = ?;",
            (topic_id,),
        )
        for question_id, text in cur.fetchall():
            opt_cur = self.connection.execute(
                "SELECT option_text, is_correct FROM options "
                "WHERE question_id = ? ORDER BY option_id;",
                (question_id,),
            )
            options = opt_cur.fetchall()
            questions.append(
                {
                    "question_id": question_id,
                    "text": text,
                    "options": [o[0] for o in options],
                    "correct_index": next(
                        i for i, o in enumerate(options) if o[1]
                    ),
                }
            )
        return questions

    def close(self) -> None:
        self.connection.close()
