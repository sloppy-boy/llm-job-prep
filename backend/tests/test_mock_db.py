from app.tools.mock_db import get_order, get_logistics, create_refund

def test_get_order_found():
    assert get_order("20260811001")["status"] == "已发货"

def test_get_order_missing():
    assert get_order("999999") is None

def test_get_logistics():
    assert len(get_logistics("20260811001")) >= 1

def test_create_refund():
    r = create_refund("20260811003", "质量问题")
    assert r["status"] == "已申请" and r["order_id"] == "20260811003"
