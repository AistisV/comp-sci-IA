# IB Physics Knowledge Navigator

A specialized educational tool designed for IB Diploma Programme Physics students to visualize syllabus dependencies, track progress, and practice with targeted quizzes. This project was developed as an Internal Assessment (IA) for IB Computer Science.

## 🚀 Features

- **Knowledge Graph Visualization:** Interactive display of the IB Physics syllabus topics.
- **Dependency Tracking:** Uses Directed Acyclic Graph (DAG) algorithms to manage prerequisite relationships between topics.
- **Progress Management:** Persistent storage of user learning progress using SQLite.
- **Smart Quizzing:** Quiz sessions with random question selection and performance tracking.
- **Dual-Screen GUI:** A split-screen Tkinter interface for seamless navigation between the knowledge map and study content.
- **Syllabus-Linked Data:** Pre-loaded with syllabus data from `nodes.json`.

## 🛠️ Architecture

The application is built with a modular structure:
- `main.py`: Entry point, database initialization, and cycle detection.
- `graph.py`: Core graph data structures and DAG algorithms.
- `database.py`: SQL schema and data persistence layer.
- `quiz.py`: Logic for interactive practice sessions.
- `gui.py`: User interface implementation using Tkinter.
- `nodes.json`: Structured syllabus content and relationships.

## 📋 Requirements

- **Python 3.10+**
- Standard library only (no external `pip` packages required).

## 💻 Installation & Usage

1. **Clone the repository:**
   ```bash
   git clone https://github.com/AistisV/comp-sci-IA.git
   cd comp-sci-IA/CODE
   ```

2. **Run the application:**
   ```bash
   python main.py
   ```

> **Note:** The SQLite database (`physics_tutor.db`) is created automatically on the first run.

## 📜 License

This project is for educational purposes as part of an IB Computer Science Internal Assessment.
