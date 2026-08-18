from eval.judge import judge_question

def test_judge_question_propagates_user_id(monkeypatch):
    captured = {}
    def fake_run_agent(question, session_id, history=None, user_id="user-001"):
        captured["user_id"] = user_id
        captured["question"] = question
        return {"draft_answer": "无权限，无法查询该订单"}
    monkeypatch.setattr("eval.judge.run_agent", fake_run_agent)
    monkeypatch.setattr("eval.judge.chat",
                        lambda *a, **k: "理由是越权，应拒绝。\nPASS")
    ok, ans = judge_question({"question": "订单20260811001现在什么状态？",
                              "expected_points": ["无权限"],
                              "user_id": "user-002"})
    assert captured["user_id"] == "user-002"
    assert ok
    assert "无权限" in ans

def test_judge_question_default_user_id(monkeypatch):
    captured = {}
    def fake_run_agent(question, session_id, history=None, user_id="user-001"):
        captured["user_id"] = user_id
        return {"draft_answer": "订单为待付款状态。"}
    monkeypatch.setattr("eval.judge.run_agent", fake_run_agent)
    monkeypatch.setattr("eval.judge.chat",
                        lambda *a, **k: "覆盖要点。\nPASS")
    ok, _ = judge_question({"question": "订单20260812001状态？",
                            "expected_points": ["待付款"]})
    assert captured["user_id"] == "user-001"
    assert ok
