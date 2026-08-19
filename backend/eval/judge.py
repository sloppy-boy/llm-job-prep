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

def _select_subset(data, limit, seed=42):
    """Build a subset for one run: ALL new questions + stratified sample of existing.

    Keeps category balance: existing questions are sampled per category
    proportional to their counts, so the subset still covers every category.
    Used to stress-test generalization (new questions) without a full-bank rerun.
    """
    if limit <= 0 or len(data) <= limit:
        return data
    new = [q for q in data if q.get("new")]
    existing = [q for q in data if not q.get("new")]
    if len(new) >= limit:
        return new[:limit]
    from collections import Counter, defaultdict
    import random
    rng = random.Random(seed)
    fill = limit - len(new)
    by_cat = defaultdict(list)
    for q in existing:
        by_cat[q["category"]].append(q)
    counts = Counter(q["category"] for q in existing)
    total_old = sum(counts.values())
    alloc = {c: max(1, counts[c] * fill // total_old) for c in by_cat}
    diff = fill - sum(alloc.values())
    for c in sorted(by_cat, key=lambda c: -counts[c]):
        while diff > 0:
            room = min(len(by_cat[c]) - alloc[c], diff)
            if room <= 0:
                break
            alloc[c] += room
            diff -= room
        if diff <= 0:
            break
    picks = []
    for c in by_cat:
        n = min(alloc[c], len(by_cat[c]))
        picks.extend(rng.sample(by_cat[c], n))
    return new + picks


def main():
    import argparse
    _check_store()
    parser = argparse.ArgumentParser(description="Run ecommerce agent eval")
    parser.add_argument("--limit", type=int, default=0,
                        help="run at most N questions: all new + stratified sample of existing")
    args = parser.parse_args()

    q_path = Path(__file__).parent / "questions.json"
    data = json.loads(q_path.read_text(encoding="utf-8"))
    if args.limit:
        data = _select_subset(data, args.limit)
        print(f"评测子集（--limit {args.limit}）：新题 {sum(1 for q in data if q.get('new'))} + 老题 {sum(1 for q in data if not q.get('new'))}")

    stats, bad = {}, []
    split = {"new": {"pass": 0, "total": 0}, "old": {"pass": 0, "total": 0}}
    for i, item in enumerate(data, 1):
        print(f"[{i}/{len(data)}] {item['category']}: {item['question']}")
        ok, answer = judge_question(item)
        stats.setdefault(item["category"], {"pass": 0, "total": 0})
        stats[item["category"]]["total"] += 1
        key = "new" if item.get("new") else "old"
        split[key]["total"] += 1
        if ok:
            stats[item["category"]]["pass"] += 1
            split[key]["pass"] += 1
        else:
            bad.append({"category": item["category"], "question": item["question"],
                        "answer": answer[:120], "new": bool(item.get("new"))})
    for cat, s in stats.items():
        print(f"{cat}: {s['pass']}/{s['total']} = {s['pass']/s['total']:.0%}")
    total_p = sum(s['pass'] for s in stats.values())
    total_t = sum(s['total'] for s in stats.values())
    print(f"\n总准确率: {total_p}/{total_t} = {total_p/total_t:.0%}")
    print(f"老题(题库内): {split['old']['pass']}/{split['old']['total']} = {split['old']['pass']/split['old']['total']:.0%}")
    print(f"新题(题库外泛化): {split['new']['pass']}/{split['new']['total']} = {split['new']['pass']/split['new']['total']:.0%}")
    print("\nBadcase:")
    for b in bad:
        tag = "[新]" if b["new"] else "[老]"
        print(f"- {tag} {b['category']} | {b['question']} → {b['answer']}")

if __name__ == "__main__":
    main()
