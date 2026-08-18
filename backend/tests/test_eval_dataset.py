import json
from pathlib import Path

EXPECTED_COUNTS = {"order": 10, "logistics": 6, "policy": 22,
                   "product": 18, "chitchat": 8, "edge": 14}

def _questions():
    p = Path(__file__).resolve().parents[1] / "eval" / "questions.json"
    return json.loads(p.read_text(encoding="utf-8"))

def test_total_count_is_78():
    assert len(_questions()) == 78

def test_category_counts():
    from collections import Counter
    assert dict(Counter(q["category"] for q in _questions())) == EXPECTED_COUNTS

def test_every_question_has_question_and_points():
    for q in _questions():
        assert q["question"].strip(), "empty question"
        assert isinstance(q["expected_points"], list) and q["expected_points"]

def test_user_id_questions_are_edge():
    for q in _questions():
        if "user_id" in q:
            assert q["category"] == "edge", "user_id 只允许出现在 edge 类"
