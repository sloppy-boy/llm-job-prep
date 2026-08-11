import time
from openai import OpenAI
from app.config import settings
from app import metrics

_client = OpenAI(api_key=settings.deepseek_api_key, base_url="https://api.deepseek.com")

def _chat_once(messages, tools, model, stream):
    kwargs = dict(model=model, messages=messages, tools=tools, stream=stream)
    # stream_options 仅流式时合法，非流式传会校验报错
    if stream:
        kwargs["stream_options"] = {"include_usage": True}
    return _client.chat.completions.create(**kwargs)

def _finalize(resp, stream):
    """归一化返回：流式原样返回；_chat_once 已被 mock 为 str 时直接返回；否则从响应对象提取文本并记录 token。"""
    if stream or isinstance(resp, str):
        return resp
    metrics.record_tokens(resp.usage.total_tokens if resp.usage else 0)
    return resp.choices[0].message.content

def chat(messages, tools=None, stream=False):
    """带指数退避重试与降级的主调用。失败最终抛异常，由上层兜底。"""
    last_err = None
    for attempt in range(3):
        try:
            return _finalize(_chat_once(messages, tools, settings.model_primary, stream), stream)
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    # 主模型重试失败，降级备用模型（不再重试，异常向上抛给调用方处理）
    return _finalize(_chat_once(messages, tools, settings.model_fallback, stream), stream)
