import threading

# 估算单价（元/百万 token，deepseek-chat 2025 公开定价：输入缓存未命中 2 元、输出 8 元）。
# 实际成本随模型、缓存命中率、供应商（降级到 SiliconFlow 时单价不同）变化——
# 这里的 total_cost_yuan 是量级估算，不宣称精确计费。
INPUT_YUAN_PER_1M = 2.0
OUTPUT_YUAN_PER_1M = 8.0

_lock = threading.Lock()
_state = {"requests": 0, "latency_sum_ms": 0.0, "input_tokens": 0, "output_tokens": 0,
          "rejected": {"ratelimit": 0, "auth": 0}}


def record_request(latency_ms: float):
    with _lock:
        _state["requests"] += 1
        _state["latency_sum_ms"] += latency_ms


def record_tokens(input_tokens: int, output_tokens: int = 0):
    """记录本次 LLM 调用的输入/输出 token（分开记，成本按各自单价估算）。
    兼容旧调用（只传一个参数时按总 token 计入 input，成本口径不变）。"""
    with _lock:
        _state["input_tokens"] += max(0, input_tokens)
        _state["output_tokens"] += max(0, output_tokens)


def record_rejected(reason: str):
    with _lock:
        _state["rejected"][reason] = _state["rejected"].get(reason, 0) + 1


def snapshot() -> dict:
    with _lock:
        reqs = _state["requests"]
        total_tokens = _state["input_tokens"] + _state["output_tokens"]
        cost = (_state["input_tokens"] * INPUT_YUAN_PER_1M
                + _state["output_tokens"] * OUTPUT_YUAN_PER_1M) / 1_000_000
        return {
            "requests": reqs,
            "avg_latency_ms": round(_state["latency_sum_ms"] / reqs, 2) if reqs else 0,
            "input_tokens": _state["input_tokens"],
            "output_tokens": _state["output_tokens"],
            "total_tokens": total_tokens,
            # 估算成本（元）：按 deepseek-chat 输入/输出单价分别计，非精确计费
            "total_cost_yuan": round(cost, 4),
            "rejected": dict(_state["rejected"]),
        }
