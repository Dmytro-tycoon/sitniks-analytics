"""
Повторні продажі: індекс «перша врахована покупка» кожного клієнта.

Клієнт = нормалізований телефон (останні 10 цифр), бо в одного клієнта в
Sitniks бувають дві картки; без телефону — id картки. Покупка = замовлення з
врахованим статусом (order_status.py). Продаж повторний, якщо в клієнта вже
була врахована покупка раніше за це замовлення.

Індекс лежить у data/client_first_purchase.json (поза git — там телефони):
    python -m src.analyzer.repeat_clients build     # разово: уся історія з 2024 р.
Далі скрипти дописують у нього покупки обробленого дня (update_index).
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional

import pytz

from src.analyzer.order_status import is_countable_order

KIEV_TZ = pytz.timezone("Europe/Kiev")
INDEX_PATH = Path(os.getenv("REPEAT_INDEX_PATH") or
                  Path(__file__).resolve().parent.parent.parent / "data" / "client_first_purchase.json")
HISTORY_START = datetime(2024, 1, 1, tzinfo=pytz.utc)


def client_key(order: dict) -> Optional[str]:
    client = order.get("client") or {}
    digits = re.sub(r"\D", "", client.get("phone") or "")
    if len(digits) >= 9:
        return digits[-10:]
    return f"id:{client['id']}" if client.get("id") else None


def _created(order: dict) -> str:
    return datetime.fromisoformat(order["createdAt"].replace("Z", "+00:00")).isoformat()


def update_index(index: Dict[str, list], orders: Iterable[dict]) -> int:
    """Дописує врахованим покупкам першу дату. Повертає к-сть змінених ключів."""
    changed = 0
    for o in orders:
        key = client_key(o)
        if not key or not is_countable_order(o) or not o.get("createdAt"):
            continue
        ts = _created(o)
        if key not in index or ts < index[key][0]:
            index[key] = [ts, o.get("id")]
            changed += 1
    return changed


def is_repeat(order: dict, index: Dict[str, list]) -> bool:
    key = client_key(order)
    first = index.get(key) if key else None
    return bool(first) and first[1] != order.get("id") and first[0] < _created(order)


def load_index() -> Dict[str, list]:
    if not INDEX_PATH.exists():
        raise FileNotFoundError(
            f"Немає {INDEX_PATH}. Спершу: python -m src.analyzer.repeat_clients build")
    return json.loads(INDEX_PATH.read_text())["clients"]


def save_index(index: Dict[str, list]):
    INDEX_PATH.parent.mkdir(exist_ok=True)
    INDEX_PATH.write_text(json.dumps(
        {"updated_at": datetime.now(KIEV_TZ).isoformat(), "clients": index}, ensure_ascii=False))


async def build_index() -> Dict[str, list]:
    """Уся історія помісячно (менші сторінки, легше переживає 429)."""
    from src.sitniks.client import SitniksClient
    index: Dict[str, list] = {}
    sitniks = SitniksClient()
    try:
        start = HISTORY_START
        now = datetime.now(pytz.utc)
        while start < now:
            end = datetime(start.year + (start.month == 12), start.month % 12 + 1, 1, tzinfo=pytz.utc)
            orders = await sitniks.get_orders_exact(start, min(end, now))
            update_index(index, orders)
            print(f"  {start:%Y-%m}: {len(orders)} замовлень, клієнтів у індексі {len(index)}", flush=True)
            start = end
    finally:
        await sitniks.close()
    return index


if __name__ == "__main__" and sys.argv[1:] == ["build"]:
    idx = asyncio.run(build_index())
    save_index(idx)
    print(f"✅ {len(idx)} клієнтів → {INDEX_PATH}")
