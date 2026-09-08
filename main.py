"""
main.py — Entry point (Figure 5: App Launch flow)

    App Launch
        -> Initialize DB & Parse JSON
        -> Cycle Detected in Graph?
             Yes -> Show Error Popup -> Exit
             No  -> Render Full Graph & Navigator Sidebar
"""

import os
import sys
import tkinter as tk
from tkinter import messagebox

from database import DatabaseManager
from quiz import QuizManager
from gui import App

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "physics_tutor.db")
JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes.json")


def main() -> None:
    db = DatabaseManager(DB_PATH)
    db.initialise_db()
    db.seed_from_json(JSON_PATH)

    graph = db.load_graph()

    if graph.detect_cycles():
        # Figure 5: "Cycle Detected in Graph? -> Yes -> Show Error Popup -> Exit"
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Invalid Syllabus Data",
            "The syllabus data contains a circular prerequisite chain and "
            "cannot be loaded. Please check nodes.json and fix the cycle "
            "before restarting the application.",
        )
        root.destroy()
        db.close()
        sys.exit(1)

    # Self-healing sweep: release any topic that is still "Locked" in
    # the save file but no longer has a Failed/Locked parent. Runs on
    # every launch so a save file is always consistent, even one
    # written by an older version of this app with a since-fixed unlock
    # bug (see graph.reconcile_locks and evaluate_unlock docstrings).
    for topic_id in graph.reconcile_locks():
        db.save_progress(topic_id, graph.nodes[topic_id].status)

    quiz = QuizManager(db)

    root = tk.Tk()
    app = App(root, graph, db, quiz)
    try:
        root.mainloop()
    finally:
        db.close()


if __name__ == "__main__":
    main()
