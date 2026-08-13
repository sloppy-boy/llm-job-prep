import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def _ratelimit_off():
    """默认关闭限流，避免共享 dev-local-key 的既有用例被全局配额打到 429；限流用例自行开启。"""
    prev = settings.ratelimit_enabled
    settings.ratelimit_enabled = False
    yield
    settings.ratelimit_enabled = prev
