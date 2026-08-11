import sqlite3, json
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "mock_orders.db"

ORDERS = [
    {"order_id": "20260811001", "status": "已发货", "items": "智能音箱 x1", "amount": 299.0, "created": "2026-08-10"},
    {"order_id": "20260811002", "status": "运输中", "items": "蓝牙耳机 x1", "amount": 199.0, "created": "2026-08-11"},
    {"order_id": "20260811003", "status": "已签收", "items": "数据线 x2", "amount": 39.9,  "created": "2026-08-08"},
    {"order_id": "20260811004", "status": "退款中", "items": "充电宝 x1", "amount": 129.0, "created": "2026-08-09"},
]
LOGISTICS = {
    "20260811001": [("08-10 20:00", "商家已发货"), ("08-11 08:00", "到达本地分拨中心")],
    "20260811002": [("08-11 09:00", "揽收"), ("08-11 14:00", "运输中")],
}

def _conn():
    Path.mkdir(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS orders(
        order_id TEXT PRIMARY KEY, status TEXT, items TEXT, amount REAL, created TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS refunds(
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, reason TEXT, status TEXT DEFAULT '已申请')""")
    return conn

def get_order(order_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if row is None:
        # 首次运行 seed
        for o in ORDERS:
            conn.execute("INSERT OR IGNORE INTO orders VALUES (?,?,?,?,?)",
                         (o["order_id"], o["status"], o["items"], o["amount"], o["created"]))
        conn.commit()
        row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    conn.close()
    return None if row is None else {"order_id": row[0], "status": row[1], "items": row[2], "amount": row[3], "created": row[4]}

def get_logistics(order_id: str) -> list[dict]:
    return [{"time": t, "event": e} for t, e in LOGISTICS.get(order_id, [])]

def create_refund(order_id: str, reason: str) -> dict:
    conn = _conn()
    cur = conn.execute("INSERT INTO refunds(order_id, reason) VALUES (?,?)", (order_id, reason))
    conn.commit()
    refund_id = cur.lastrowid
    conn.close()
    return {"refund_id": f"R{refund_id}", "order_id": order_id, "reason": reason, "status": "已申请"}

def escalate(session_id: str) -> dict:
    return {"session_id": session_id, "status": "已转人工"}
