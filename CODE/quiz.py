"""
quiz.py — Module 3: Quiz Logic (QuizManager)

Handles a single quiz attempt (randomised question order, scoring) and
the recovery stack used to walk the user back down the chain of failed
prerequisites (Figure 6, Figure 7).
"""

from __future__ import annotations

import random


class QuizManager:
    """
    current_questions : the (shuffled) list of question dicts for the
                         topic currently being quizzed
    score             : number of correct answers so far this attempt
    recovery_stack    : LIFO stack of topic_ids the user must re-pass,
                         pushed onto during knowledge-gap diagnosis and
                         popped as each recovery quiz is completed
                         (Figure 7's "Path Recovery Stack", SC7)
    """

    def __init__(self, db):
        self.db = db
        self.current_questions: list[dict] = []
        self.current_topic_id: str | None = None
        self._answers: list[bool] = []
        self.score = 0
        self.recovery_stack: list[str] = []

    # ------------------------------------------------------------------
    # SC5: randomised question picker
    # ------------------------------------------------------------------

    def initialize_quiz(self, topic_id: str) -> list[dict]:
        """Loads and shuffles this topic's questions, resets the score."""
        self.current_topic_id = topic_id
        questions = list(self.db.get_questions(topic_id))
        random.shuffle(questions)
        for q in questions:
            # Also shuffle each question's own option order so repeat
            # attempts don't always show the answer in the same slot.
            correct_text = q["options"][q["correct_index"]]
            random.shuffle(q["options"])
            q["correct_index"] = q["options"].index(correct_text)
        self.current_questions = questions
        self._answers = []
        self.score = 0
        return self.current_questions

    def submit_answer(self, q_index: int, chosen_index: int) -> bool:
        """Records whether the answer to question q_index was correct."""
        correct = chosen_index == self.current_questions[q_index]["correct_index"]
        self._answers.append(correct)
        if correct:
            self.score += 1
        return correct

    def evaluate_attempt(self) -> bool:
        """
        Returns True (pass) if the user scored at least half marks,
        False otherwise. A quiz is only "complete" once every question
        has been answered (Figure 6: 'More Questions Remaining?').
        """
        total = len(self.current_questions)
        return total > 0 and self.score >= (total / 2)

    @property
    def total_questions(self) -> int:
        return len(self.current_questions)

    # ------------------------------------------------------------------
    # SC7: recovery stack (LIFO)
    # ------------------------------------------------------------------

    def push_recovery(self, topic_id: str) -> None:
        self.recovery_stack.append(topic_id)

    def pop_next_recovery_topic(self) -> str | None:
        """Pops and returns the next topic to re-test, or None if empty."""
        if self.recovery_stack:
            return self.recovery_stack.pop()
        return None

    def recovery_is_empty(self) -> bool:
        return len(self.recovery_stack) == 0
