"""
quiz.py
-------
Quiz session management for the IB Physics Knowledge Navigator.

A QuizSession encapsulates one quiz attempt on a single topic:
  - picks a random subset of questions from the database (SC5)
  - records each answer submitted
  - determines pass / fail when all questions are answered

Pass policy: the student must answer ALL questions correctly.
"""

import random
from database import get_questions_for_topic

QUESTIONS_PER_QUIZ = 2   # number of questions drawn per attempt


class QuizSession:
    """
    Manages a single quiz attempt.

    Parameters
    ----------
    topic_id   : str   database ID of the topic being quizzed
    topic_name : str   human-readable name (for display only)
    """

    def __init__(self, topic_id: str, topic_name: str) -> None:
        self.topic_id   = topic_id
        self.topic_name = topic_name

        # Randomly sample questions for this attempt (SC5).
        all_questions = get_questions_for_topic(topic_id)
        n = min(QUESTIONS_PER_QUIZ, len(all_questions))
        self.questions: list[dict] = random.sample(all_questions, n)

        self.current_index: int  = 0
        self.correct_count: int  = 0
        # Each entry: (selected_index, correct_index, is_correct)
        self.answers: list[tuple[int, int, bool]] = []

    # ── Question access ────────────────────────────────────────────────────────

    def current_question(self) -> dict | None:
        """Return the current question dict, or None if the quiz is finished."""
        if self.current_index < len(self.questions):
            return self.questions[self.current_index]
        return None

    def progress_label(self) -> str:
        """Return a human-readable progress string, e.g. 'Question 1 of 2'."""
        return f"Question {self.current_index + 1} of {len(self.questions)}"

    # ── Answer submission ──────────────────────────────────────────────────────

    def submit_answer(self, selected_index: int) -> bool:
        """
        Record the student's answer for the current question.

        Parameters
        ----------
        selected_index : int  index of the chosen option (0-based)

        Returns
        -------
        bool  True if the answer was correct.
        """
        q = self.current_question()
        if q is None:
            return False

        is_correct = (selected_index == q["correct_index"])
        if is_correct:
            self.correct_count += 1

        self.answers.append((selected_index, q["correct_index"], is_correct))
        self.current_index += 1
        return is_correct

    # ── Session state ──────────────────────────────────────────────────────────

    def is_finished(self) -> bool:
        """Return True when all questions have been answered."""
        return self.current_index >= len(self.questions)

    def passed(self) -> bool:
        """
        Return True if the student answered every question correctly.
        Only meaningful after is_finished() returns True.
        """
        return self.is_finished() and (self.correct_count == len(self.questions))

    def score(self) -> tuple[int, int]:
        """Return (correct_count, total_questions)."""
        return self.correct_count, len(self.questions)
