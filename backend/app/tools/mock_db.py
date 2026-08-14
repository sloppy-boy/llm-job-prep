import sqlite3, json
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "mock_orders.db"

# 演示用户：订单都归属 user-001（demo 前端默认用户）
DEMO_USER = "user-001"
ORDERS = [
    {"order_id": "20260811001", "status": "已发货", "items": "智能音箱 x1", "amount": 299.0, "created": "2026-08-10", "user_id": DEMO_USER},
    {"order_id": "20260811002", "status": "运输中", "items": "蓝牙耳机 x1", "amount": 199.0, "created": "2026-08-11", "user_id": DEMO_USER},
    {"order_id": "20260811003", "status": "已签收", "items": "数据线 x2", "amount": 39.9,  "created": "2026-08-08", "user_id": DEMO_USER},
    {"order_id": "20260811004", "status": "退款中", "items": "充电宝 x1", "amount": 129.0, "created": "2026-08-09", "user_id": DEMO_USER},
]
LOGISTICS = {
    "20260811001": [("08-10 20:00", "商家已发货"), ("08-11 08:00", "到达本地分拨中心")],
    "20260811002": [("08-11 09:00", "揽收"), ("08-11 14:00", "运输中")],
}

_initialized = False


def _conn():
    Path.mkdir(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS orders(
        order_id TEXT PRIMARY KEY, status TEXT, items TEXT, amount REAL, created TEXT, user_id TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS refunds(
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, reason TEXT, status TEXT DEFAULT '已申请')""")
    return conn


def _init_db():
    """一次性初始化：建表 + 种子数据 + 兼容旧库。只在首次导入时执行一次，
    不再放进每次查询路径（此前缺失订单每次查询都会重跑 seed/ALTER）。"""
    global _initialized
    if _initialized:
        return
    conn = _conn()
    try:
        # 兼容旧库（orders 表无 user_id 列时补上）
        try:
            conn.execute("ALTER TABLE orders ADD COLUMN user_id TEXT")
        except Exception:
            pass
        for o in ORDERS:
            conn.execute("INSERT OR IGNORE INTO orders VALUES (?,?,?,?,?,?)",
                         (o["order_id"], o["status"], o["items"], o["amount"], o["created"], o["user_id"]))
        # 补旧数据的归属（升级前已存在的订单）
        conn.execute("UPDATE orders SET user_id=? WHERE user_id IS NULL", (DEMO_USER,))
        conn.commit()
        _initialized = True
    finally:
        conn.close()


def _owned_order(order_id: str, user_id: str) -> dict | None:
    """查订单行并做归属校验。返回 (dict | None, error)。"""
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    d = {"order_id": row[0], "status": row[1], "items": row[2], "amount": row[3],
         "created": row[4], "user_id": row[5]}
    if d.get("user_id") and d["user_id"] != user_id:
        return {"error": "无权限", "order_id": order_id}
    return d


def get_order(order_id: str, user_id: str) -> dict | None:
    """查订单 + 归属校验。不存在→None；越权→{'error':'无权限'}；否则订单 dict。"""
    _init_db()
    d = _owned_order(order_id, user_id)
    return d


def get_logistics(order_id: str, user_id: str) -> list[dict] | dict:
    """查物流 + 归属校验（与 get_order 同等：A 不能查 B 的物流）。
    订单不存在→{'error':'订单不存在'}；越权→{'error':'无权限'}；有记录→列表；无记录→空列表。"""
    _init_db()
    owned = _owned_order(order_id, user_id)
    if owned is None:
        return {"error": "订单不存在", "order_id": order_id}
    if "error" in owned:
        return owned
    return [{"time": t, "event": e} for t, e in LOGISTICS.get(order_id, [])]


def create_refund(order_id: str, reason: str, user_id: str) -> dict:
    """发起退款 + 归属校验：只能退自己的订单。"""
    _init_db()
    conn = _conn()
    try:
        row = conn.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,)).fetchone()
        if row is None or (row[0] and row[0] != user_id):
            return {"error": "无权限", "order_id": order_id}
        cur = conn.execute("INSERT INTO refunds(order_id, reason) VALUES (?,?)", (order_id, reason))
        conn.commit()
        refund_id = cur.lastrowid
    finally:
        conn.close()
    return {"refund_id": f"R{refund_id}", "order_id": order_id, "reason": reason, "status": "已申请"}


def escalate(session_id: str) -> dict:
    return {"session_id": session_id, "status": "已转人工"}
