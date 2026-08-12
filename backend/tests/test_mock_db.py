from app.tools.mock_db import get_order, get_logistics, create_refund

def test_get_order_found():
    assert get_order("20260811001", "user-001")["status"] == "已发货"

def test_get_order_missing():
    assert get_order("999999", "user-001") is None

def test_get_order_denied_for_other_user():
    """越权：user-002 查 user-001 的订单 → 无权限"""
    assert get_order("20260811001", "user-002") == {"error": "无权限", "order_id": "20260811001"}

def test_get_logistics():
    assert len(get_logistics("20260811001")) >= 1

def test_create_refund():
    r = create_refund("20260811003", "质量问题", "user-001")
    assert r["status"] == "已申请" and r["order_id"] == "20260811003"

def test_create_refund_denied_for_other_user():
    """越权：只能退自己的订单"""
    assert create_refund("20260811003", "质量问题", "user-002") == {"error": "无权限", "order_id": "20260811003"}
