"""
Клієнт LiqPay: підпис, checkout-URL, перевірка callback.

Алгоритм LiqPay (Internet Acquiring / Checkout):
    data      = base64( json_utf8(params) )
    signature = base64( sha1( private_key + data + private_key ) )

Чистий модуль без IO — безпечно викликати з async-коду.
Документація: https://www.liqpay.ua/doc/api/internet_acquiring/checkout
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Optional

CHECKOUT_URL = "https://www.liqpay.ua/api/3/checkout"


class LiqPay:
    def __init__(self, public_key: str, private_key: str) -> None:
        if not public_key or not private_key:
            raise ValueError("Потрібні public_key та private_key LiqPay")
        self.public_key = public_key
        self.private_key = private_key

    # ── підпис ────────────────────────────────────────────────────────────────
    def _encode_data(self, params: dict[str, Any]) -> str:
        raw = json.dumps(params, ensure_ascii=False).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _make_signature(self, data: str) -> str:
        to_sign = f"{self.private_key}{data}{self.private_key}".encode("utf-8")
        return base64.b64encode(hashlib.sha1(to_sign).digest()).decode("ascii")

    # ── створення посилання ─────────────────────────────────────────────────────
    def checkout_url(self, params: dict[str, Any]) -> str:
        merged = {"public_key": self.public_key, "version": "3", **params}
        data = self._encode_data(merged)
        signature = self._make_signature(data)
        return f"{CHECKOUT_URL}?data={data}&signature={signature}"

    # ── перевірка callback (server_url) ─────────────────────────────────────────
    def verify_signature(self, data: str, signature: str) -> bool:
        expected = self._make_signature(data)
        return hmac.compare_digest(expected, signature)

    def decode_data(self, data: str) -> dict[str, Any]:
        return json.loads(base64.b64decode(data))

    def parse_callback(self, data: str, signature: str) -> dict[str, Any]:
        """Перевіряє підпис і повертає розкодовані дані. ValueError — якщо підпис невалідний."""
        if not self.verify_signature(data, signature):
            raise ValueError("Невалідний підпис callback (можлива підробка)")
        return self.decode_data(data)


def build_payparts_payment(
    amount: float,
    order_id: str,
    description: str,
    *,
    paytype: str = "payparts",
    currency: str = "UAH",
    result_url: Optional[str] = None,
    server_url: Optional[str] = None,
    language: str = "uk",
) -> dict[str, Any]:
    """
    Параметри платежу «оплата частинами».

    paytype:
        "payparts"             — Оплата частинами
        "moment_part"          — Миттєва розстрочка
        "payparts,moment_part" — обидва варіанти
    Кількість платежів (2–25) покупець обирає сам на сторінці LiqPay.
    """
    params: dict[str, Any] = {
        "action": "pay",
        "amount": f"{amount:.2f}",
        "currency": currency,
        "description": description,
        "order_id": order_id,
        "paytypes": paytype,
        "language": language,
    }
    if result_url:
        params["result_url"] = result_url
    if server_url:
        params["server_url"] = server_url
    return params
