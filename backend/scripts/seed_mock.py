import sys
from pathlib import Path

# 直接运行本脚本时 sys.path[0] 是 scripts/，把 backend/ 加进去以便导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.mock_db import get_order, create_refund

if __name__ == "__main__":
    for oid in ["20260811001", "20260811002"]:
        print(get_order(oid))
    print(create_refund("20260811002", "不想要了"))
