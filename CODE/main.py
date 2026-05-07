"""
main.py
-------
Entry point for the IB Physics Knowledge Navigator.

Start-up sequence:
  1. Initialise the SQLite database (create tables if absent).
  2. Seed static data from nodes.json on first run.
  3. Load the graph and run DFS cycle detection to validate the data (SC1).
  4. Launch the Tkinter GUI.
"""

import sys
import tkinter as tk
from tkinter import messagebox

import database
from graph import PhysicsGraph
from gui   import App


def main() -> None:
    # ── Step 1: database schema ────────────────────────────────────────────
    database.init_db()

    # ── Step 2: first-run seed ─────────────────────────────────────────────
    if not database.is_seeded():
        try:
            database.seed_from_json()
            print("[INFO] Database seeded from nodes.json")
        except FileNotFoundError:
            # Show a GUI error before exiting if the JSON is missing.
            _error("nodes.json not found.\n\n"
                   "Place nodes.json in the same directory as main.py.")
            return

    # ── Step 3: cycle detection ────────────────────────────────────────────
    # Load the graph purely to validate the DAG structure.
    # The GUI will load its own instance; this graph is discarded afterwards.
    validation_graph = PhysicsGraph()
    if validation_graph.dfs_cycle_detect():
        _error("Circular dependency detected in nodes.json.\n\n"
               "The graph must be a Directed Acyclic Graph (DAG).\n"
               "Please correct the prerequisite links and restart.")
        return
    print("[INFO] Graph validated – no cycles detected.")

    # ── Step 4: launch GUI ─────────────────────────────────────────────────
    root = tk.Tk()
    root.tk.call("tk", "scaling", 1.0)   # crisp rendering on HiDPI screens
    app  = App(root)                      # noqa: F841 (kept alive via root loop)
    root.mainloop()


def _error(message: str) -> None:
    """Display a fatal error dialog (works even if the main window isn't up)."""
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror("Startup Error", message)
    _root.destroy()
    sys.exit(1)


if __name__ == "__main__":
    main()
