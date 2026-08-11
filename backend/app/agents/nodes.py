from app.rag.retrieve import hybrid_search, rerank
from app.llm import chat
from app.agents.state import AgentState

SYSTEM = "你是电商售后智能客服。只基于提供的检索资料回答；资料不足时明确说不知道并建议转人工，绝不编造。"

def router_node(state: AgentState) -> dict:
    """判断问题域：chitchat 寒暄 / order 订单 / policy 其他文档问题。"""
    q = state["question"]
    if any(k in q for k in ["你好", "在吗", "谢谢"]):
        domain = "chitchat"
    elif any(k in q for k in ["订单", "物流", "发货"]):
        domain = "order"
    else:
        domain = "policy"
    return {"domain": domain}

def retriever_node(state: AgentState) -> dict:
    """检索 + 重排。跨任务契约：RAG 层失败会抛异常，必须兜底为空，让 writer 走诚实话术。"""
    if state["domain"] == "chitchat":
        return {"retrieved_chunks": []}
    try:
        docs = hybrid_search(state["question"])
        return {"retrieved_chunks": rerank(state["question"], docs)}
    except Exception:
        return {"retrieved_chunks": []}

def writer_node(state: AgentState) -> dict:
    """基于检索资料组织回答；无资料时必须如实告知并建议转人工，禁止编造。"""
    msgs = [{"role": "system", "content": SYSTEM}]
    msgs.extend(state.get("history", []))
    if state["domain"] == "chitchat":
        user = f"用户寒暄：{state['question']}\n请礼貌简短回应，并引导用户提出售后问题。"
    elif not state.get("retrieved_chunks"):
        user = f"知识库没有检索到相关内容。请如实告诉用户'暂时没有找到相关说明，可转人工处理'，不要编造。\n问题：{state['question']}"
    else:
        ctx = "\n\n".join(f"[{d['title']}]\n{d['text']}" for d in state["retrieved_chunks"])
        user = f"检索资料：\n{ctx}\n\n问题：{state['question']}"
    msgs.append({"role": "user", "content": user})
    if state.get("review_comment"):
        msgs.append({"role": "user", "content": f"上次回答被审核打回，原因：{state['review_comment']}。请修正。"})
    return {"draft_answer": chat(msgs, stream=False)}

def reviewer_node(state: AgentState) -> dict:
    """审核：忠于资料？遗漏要点？编造？打回则迭代+1；审核模型失败时放行（不阻塞回答）。"""
    iteration = state.get("iteration", 0) + 1
    if state["domain"] == "chitchat":
        return {"review_status": "passed", "review_comment": "", "iteration": iteration}
    try:
        check = chat([
            {"role": "system", "content": "你是质量审核员。检查回答是否：1)忠于检索资料 2)未遗漏关键点 3)无编造。有问题输出[驳回]+原因，否则输出[通过]。"},
            {"role": "user", "content": f"资料：\n{state['retrieved_chunks']}\n\n回答：{state['draft_answer']}"},
        ], stream=False)
    except Exception:
        return {"review_status": "passed", "review_comment": "", "iteration": iteration}
    passed = "[通过]" in check
    return {"review_status": "passed" if passed else "rejected",
            "review_comment": "" if passed else check,
            "iteration": iteration}
