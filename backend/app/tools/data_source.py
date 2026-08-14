"""订单/物流/退款数据源抽象。

上层（order_tools.dispatch）通过注入的数据源调用，不直接依赖 mock 实现。
未来接真实 ERP/订单系统时，只需新增一个实现类替换注入，上层代码不变。
"""
from app.tools import mock_db


class OrderDataSource:
    """数据源契约：查订单（带归属校验）、查物流、发起退款、转人工。"""

    def get_order(self, order_id: str, user_id: str) -> dict | None:
        """查订单。校验 user_id 归属：订单不存在返回 None；越权返回 {'error': '无权限'}。"""
        raise NotImplementedError

    def get_logistics(self, order_id: str, user_id: str) -> list[dict] | dict:
        """查物流。与 get_order 同等的归属校验：订单不存在/越权返回 {'error': ...}，
        有物流数据返回列表；订单存在但无物流记录返回空列表。"""
        raise NotImplementedError

    def create_refund(self, order_id: str, reason: str, user_id: str) -> dict:
        """发起退款。越权（不是自己的订单）返回 {'error': '无权限'}。"""
        raise NotImplementedError

    def escalate(self, session_id: str) -> dict:
        raise NotImplementedError


class MockOrderDataSource(OrderDataSource):
    """基于 mock 库的实现（演示/开发用）。真实系统实现同接口后替换注入即可。"""

    def get_order(self, order_id: str, user_id: str) -> dict | None:
        return mock_db.get_order(order_id, user_id)

    def get_logistics(self, order_id: str, user_id: str) -> list[dict] | dict:
        return mock_db.get_logistics(order_id, user_id)

    def create_refund(self, order_id: str, reason: str, user_id: str) -> dict:
        return mock_db.create_refund(order_id, reason, user_id)

    def escalate(self, session_id: str) -> dict:
        return mock_db.escalate(session_id)
