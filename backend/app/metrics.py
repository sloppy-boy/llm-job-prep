import threading

_lock = threading.Lock()
_state = {"requests": 0, "latency_sum_ms": 0.0, "total_tokens": 0}

def record_request(latency_ms: float):
    with _lock:
        _state["requests"] += 1
        _state["latency_sum_ms"] += latency_ms

def record_tokens(n: int):
    with _lock:
        _state["total_tokens"] += n

def snapshot() -> dict:
    with _lock:
        reqs = _state["requests"]
        return {
            "requests": reqs,
            "avg_latency_ms": round(_state["latency_sum_ms"] / reqs, 2) if reqs else 0,
            "total_tokens": _state["total_tokens"],
            "total_cost_yuan": round(_state["total_tokens"] / 1_000_000, 4),
        }
