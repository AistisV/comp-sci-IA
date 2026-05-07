IB Physics Knowledge Navigator
================================

Requirements
------------
  Python 3.10+  (tkinter is included in all standard distributions)
  No pip packages required.

Running
-------
  python main.py

All five source files and nodes.json must be in the same folder.
The SQLite database (physics_tutor.db) is created automatically on
first run; do not delete it or progress will be reset.

File overview
-------------
  main.py      – Entry point: DB init, cycle detection, GUI launch
  database.py  – All SQL (schema, seeding, read/write)
  graph.py     – DAG representation and all graph algorithms
  quiz.py      – Quiz session (random picker + answer tracking)
  gui.py       – Tkinter split-screen interface
  nodes.json   – Syllabus data (topics, edges, questions)

Resetting progress
------------------
  Click "Reset All Progress" in the navigator sidebar, or delete
  physics_tutor.db and restart.
