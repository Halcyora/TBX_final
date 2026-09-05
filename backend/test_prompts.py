"""
Self-check for dynamic few-shot example selection (prompts.py): the most relevant examples
should surface for a targeted question, and a generic/empty question should still return k
examples rather than crashing or returning nothing.
Run directly: python test_prompts.py
"""
from prompts import _select_examples, SQL_EXAMPLES


def test_targeted_question_surfaces_matching_example():
    selected = _select_examples("What is the longest gap between consecutive transactions?", k=3)
    assert len(selected) == 3
    assert selected[0]["question"].startswith("What is the longest gap")


def test_generic_question_still_returns_k_examples():
    selected = _select_examples("tell me something", k=4)
    assert len(selected) == 4


def test_k_never_exceeds_bank_size():
    selected = _select_examples("anything", k=len(SQL_EXAMPLES) + 10)
    assert len(selected) == len(SQL_EXAMPLES)


if __name__ == "__main__":
    test_targeted_question_surfaces_matching_example()
    test_generic_question_still_returns_k_examples()
    test_k_never_exceeds_bank_size()
    print("All prompts self-checks passed.")
