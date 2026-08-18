from app.tools.mock_db import get_order, get_logistics, create_refund

def test_get_order_found():
    assert get_order("20260811001", "user-001")["status"] == "已发货"

def test_get_order_missing():
    assert get_order("999999", "user-001") is None

def test_get_order_denied_for_other_user():
    """越权：user-002 查 user-001 的订单 → 无权限"""
    assert get_order("20260811001", "user-002") == {"error": "无权限", "order_id": "20260811001"}

def test_get_logistics():
    assert len(get_logistics("20260811001", "user-001")) >= 1

def test_get_logistics_denied_for_other_user():
    """越权：user-002 查 user-001 的物流 → 无权限（与 get_order 同等归属校验）"""
    assert get_logistics("20260811001", "user-002") == {"error": "无权限", "order_id": "20260811001"}

def test_get_logistics_missing_order_returns_error():
    """不存在的订单 → error（而非空列表），避免前端渲染空物流卡片"""
    r = get_logistics("999999", "user-001")
    assert "error" in r

def test_get_logistics_own_order_without_track_returns_empty():
    """自己的订单但无物流记录（20260811003）→ 空列表，不是 error"""
    assert get_logistics("20260811003", "user-001") == []

def test_create_refund():
    r = create_refund("20260811003", "质量问题", "user-001")
    assert r["status"] == "已申请" and r["order_id"] == "20260811003"

def test_create_refund_denied_for_other_user():
    """越权：只能退自己的订单"""
    assert create_refund("20260811003", "质量问题", "user-002") == {"error": "无权限", "order_id": "20260811003"}

# ---- 评测集扩充新增（2026-08-18）----

def test_get_order_new_statuses():
    assert get_order("20260812001", "user-001")["status"] == "待付款"
    assert get_order("20260812002", "user-001")["status"] == "待发货"
    assert get_order("20260812004", "user-001")["status"] == "已完成"
    assert get_order("20260812005", "user-001")["status"] == "已取消"
    assert get_order("20260812006", "user-001")["status"] == "已发货"

def test_get_order_new_items():
    assert get_order("20260812003", "user-001")["items"] == "电饭煲 x1"

def test_get_order_new_denied_for_other_user():
    assert get_order("20260812003", "user-002") == {"error": "无权限", "order_id": "20260812003"}

def test_get_logistics_new_records():
    assert len(get_logistics("20260812004", "user-001")) >= 2
    assert len(get_logistics("20260812003", "user-001")) >= 1
    assert get_logistics("20260812006", "user-001")[0]["event"] == "商家已发货"

def test_get_logistics_03_still_empty():
    """订单 20260811003 必须保持无物流记录（既有契约）"""
    assert get_logistics("20260811003", "user-001") == []

def test_get_logistics_cancelled_order_no_record():
    """已取消订单 20260812005 无物流记录 → 空列表"""
    assert get_logistics("20260812005", "user-001") == []
