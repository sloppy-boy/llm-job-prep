import json
from pathlib import Path
from app.agents.graph import run_agent
from app.llm import chat

def judge(points: list[str], answer: str) -> bool:
    """LLM 判分：回答是否覆盖全部要点。覆盖输出 PASS，否则输出 FAIL。"""
    check = chat([
        {"role": "system", "content": "你是评测员。判断回答是否覆盖全部要点。全覆盖输出PASS，否则输出FAIL。"},
        {"role": "user", "content": f"要点：{points}\n回答：{answer}"},
    ], stream=False)
    return "PASS" in check

def main():
    q_path = Path(__file__).parent / "questions.json"
    data = json.loads(q_path.read_text(encoding="utf-8"))
    stats, bad = {}, []
    for i, item in enumerate(data, 1):
        print(f"[{i}/{len(data)}] {item['category']}: {item['question']}")
        r = run_agent(item["question"], session_id="eval")
        answer = r.get("draft_answer", "")
        ok = judge(item["expected_points"], answer)
        stats.setdefault(item["category"], {"pass": 0, "total": 0})
        stats[item["category"]]["total"] += 1
        if ok:
            stats[item["category"]]["pass"] += 1
        else:
            bad.append({"category": item["category"], "question": item["question"],
                        "answer": answer[:120]})
    for cat, s in stats.items():
        print(f"{cat}: {s['pass']}/{s['total']} = {s['pass']/s['total']:.0%}")
    total_p = sum(s['pass'] for s in stats.values())
    total_t = sum(s['total'] for s in stats.values())
    print(f"\n总准确率: {total_p}/{total_t} = {total_p/total_t:.0%}")
    print("\nBadcase:")
    for b in bad:
        print("-", b["category"], "|", b["question"], "→", b["answer"])

if __name__ == "__main__":
    main()
