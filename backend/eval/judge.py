import json
import re
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
    """LLM 判分：回答是否覆盖全部要点。注意用词不同但要点覆盖也算。

    稳定性设计：要求 judge 先简述理由、最后一行输出裁决，再解析**最后出现**的
    PASS/FAIL——实测"只输出PASS/FAIL"的极简 prompt 会把明确拒绝/完整覆盖
    的正确答案误判为 FAIL（false negative），推理先行能显著降低抖动。
    """
    check = chat([
        {"role": "system", "content": "你是严格的评测员。判断回答是否覆盖了列出的全部要点。注意：要点都覆盖了即使用词不同也算覆盖。"},
        {"role": "user", "content": f"要点：{points}\n回答：{answer}\n请先简述判断理由，最后一行只输出 PASS 或 FAIL。"},
    ], stream=False)
    # 解析裁决：理由里可能提及 PASS/FAIL 字样，取最后一次出现的才是最终裁决
    verdicts = re.findall(r"\b(PASS|FAIL)\b", check.upper())
    return bool(verdicts) and verdicts[-1] == "PASS"


def judge_question(item: dict) -> tuple[bool, str]:
    """Run one evaluation question and return (pass, answer).

    A question may override the demo user so boundary cases can verify
    order-ownership checks without changing the normal evaluation path.
    """
    r = run_agent(item["question"], session_id="eval",
                  user_id=item.get("user_id", "user-001"))
    answer = r.get("draft_answer", "")
    return judge(item["expected_points"], answer), answer

def main():
    _check_store()
    q_path = Path(__file__).parent / "questions.json"
    data = json.loads(q_path.read_text(encoding="utf-8"))
    stats, bad = {}, []
    for i, item in enumerate(data, 1):
        print(f"[{i}/{len(data)}] {item['category']}: {item['question']}")
        ok, answer = judge_question(item)
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
