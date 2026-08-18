import time
from openai import OpenAI
from app.config import settings
from app import metrics

# 主模型 client：SiliconFlow 的 DeepSeek-V4-Flash
_client = OpenAI(api_key=settings.siliconflow_api_key, base_url=settings.primary_base_url)

# 备用 client：懒加载，只有主模型重试失败后才构造
_fallback_client_inst = None


def _fallback_client() -> OpenAI:
    global _fallback_client_inst
    if _fallback_client_inst is None:
        _fallback_client_inst = OpenAI(
            api_key=settings.siliconflow_api_key, base_url=settings.fallback_base_url)
    return _fallback_client_inst


def _chat_once(messages, tools, model, stream, client):
    kwargs = dict(model=model, messages=messages, tools=tools, stream=stream)
    # stream_options 仅流式时合法，非流式传会校验报错
    if stream:
        kwargs["stream_options"] = {"include_usage": True}
    return client.chat.completions.create(**kwargs)


def _finalize(resp, stream):
    """归一化返回：流式原样返回；_chat_once 已被 mock 为 str 时直接返回；否则从响应对象提取文本并记录 token。"""
    if stream or isinstance(resp, str):
        return resp
    metrics.record_tokens(resp.usage.prompt_tokens if resp.usage else 0,
                          resp.usage.completion_tokens if resp.usage else 0)
    return resp.choices[0].message.content


def _retry(messages, tools, stream):
    """指数退避重试主模型，失败切换备用模型。"""
    last_err = None
    for attempt in range(3):
        try:
            return _chat_once(messages, tools, settings.model_primary, stream, _client)
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    # 主模型重试失败，降级备用模型（不再重试，异常向上抛给调用方处理）
    return _chat_once(messages, tools, settings.model_fallback, stream, _fallback_client())


def chat(messages, tools=None, stream=False):
    resp = _retry(messages, tools, stream)
    return _finalize(resp, stream)


def chat_with_tools(messages, tools) -> tuple[str, list]:
    """带工具调用的调用。返回 (content, tool_calls)。
    tool_calls: [{"name": str, "arguments": dict}]；无工具调用时空列表。"""
    import json as _json
    resp = _retry(messages, tools, False)
    msg = resp.choices[0].message
    tool_calls = []
    for tc in getattr(msg, "tool_calls", None) or []:
        fn = tc.function
        tool_calls.append({"name": fn.name, "arguments": _json.loads(fn.arguments or "{}")})
    metrics.record_tokens(resp.usage.prompt_tokens if resp.usage else 0,
                          resp.usage.completion_tokens if resp.usage else 0)
    return msg.content or "", tool_calls
