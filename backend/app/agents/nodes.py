import json
from app.rag.retrieve import hybrid_search, rerank
from app.llm import chat, chat_with_tools
from app.agents.state import AgentState
from app.tools import order_tools

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

def tool_node(state: AgentState) -> dict:
    """订单域：让 LLM 决定工具调用并执行；其他域直接透传空结果。失败兜底，不中断流程。"""
    if state["domain"] != "order":
        return {"tool_results": []}
    try:
        _, tool_calls = chat_with_tools([
            {"role": "system", "content": "从用户话术中提取订单号，选择合适工具。"},
            {"role": "user", "content": state["question"]},
        ], order_tools.TOOLS)
        if not tool_calls:
            return {"tool_results": [{"error": "未能识别到工具调用"}]}
        call = tool_calls[0]
        result = json.loads(order_tools.dispatch(
            call["name"], call.get("arguments", {}), user_id=state.get("user_id", "user-001")))
    except Exception:
        result = {"error": "无法解析工具调用或执行失败"}
    return {"tool_results": [result]}

def build_writer_messages(state: AgentState) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM}]
    msgs.extend(state.get("history", []))
    tool_text = ""
    if state.get("tool_results"):
        tool_text = "\n工具查询结果：" + str(state["tool_results"])
    if state["domain"] == "chitchat":
        user = f"用户寒暄：{state['question']}\n请礼貌简短回应，并引导用户提出售后问题。"
    elif state["domain"] == "order" and state.get("tool_results") and \
            isinstance(state["tool_results"][0], dict) and "error" not in state["tool_results"][0]:
        user = (f"系统已查询到订单信息。请**只基于以下工具结果**如实回答用户，"
                f"不要编造，不要被其他检索内容干扰。{tool_text}\n问题：{state['question']}")
    elif not state.get("retrieved_chunks"):
        user = f"知识库没有检索到相关内容。请如实告诉用户'暂时没有找到相关说明，可转人工处理'，不要编造。{tool_text}\n问题：{state['question']}"
    else:
        ctx = "\n\n".join(f"[{d['title']}]\n{d['text']}" for d in state["retrieved_chunks"])
        user = f"检索资料：\n{ctx}{tool_text}\n\n问题：{state['question']}"
    msgs.append({"role": "user", "content": user})
    return msgs

def writer_node(state: AgentState) -> dict:
    msgs = build_writer_messages(state)
    return {"draft_answer": chat(msgs, stream=False)}

def gate_decision(state: AgentState) -> bool:
    """前置质量闸门：资料足够才流式生成，否则走诚实兜底话术。
    order 域看工具结果（error 视为不足）；policy/product 看检索命中；chitchat 恒通过。"""
    if state["domain"] == "chitchat":
        return True
    if state["domain"] == "order":
        return bool(state.get("tool_results") and isinstance(state["tool_results"][0], dict)
                    and "error" not in state["tool_results"][0])
    return bool(state.get("retrieved_chunks"))
