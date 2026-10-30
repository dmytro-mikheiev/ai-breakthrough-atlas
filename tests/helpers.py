"""Synthetic settings shared by software tests."""

from src.settings import Settings


def defaults():
    return Settings(
        books=["Synthetic Book.txt"],
        question="AI breakthroughs and their locations",
        classifier_criteria={"keep": "Relevant", "drop": "Irrelevant", "uncertain": "Uncertain"},
    )
