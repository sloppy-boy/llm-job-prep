import json
import sys
from pathlib import Path
from app.agents.graph import run_agent
from app.llm import chat

def _check_store():
    """Qdrant 本地模式不支持多进程并发访问同一目录。
    若后端服务正占用索引，评测进程加载会失败并静默空检索，导致假性低准确率。
    启动时自检一次，失败给出明确提示，避免跑出无效结果。"""
    from app.rag.retrieve import get_store
    try:
        get_store()
    except RuntimeError as e:
        if "already accessed by another instance" in str(e):
            print("❌ Qdrant 本地索引正被占用（通常是后端服务在运行）。")
            print("   评测需要独占索引：请先停止后端（停 8000 端口进程），再重跑评测。")
            sys.exit(1)
        raise

def judge(points: list[str], answer: str) -> bool:
    """LLM 判分：回答是否覆盖全部要点。注意用词不同但要点覆盖也算。"""
    check = chat([
        {"role": "system", "content": "你是严格的评测员。判断回答是否覆盖了列出的全部要点。注意：要点都覆盖了即使用词不同也算覆盖。全部覆盖输出PASS，有任何遗漏输出FAIL。只输出PASS或FAIL。"},
        {"role": "user", "content": f"要点：{points}\n回答：{answer}"},
    ], stream=False)
    return check.strip().upper().startswith("PASS")

def main():
    _check_store()
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
