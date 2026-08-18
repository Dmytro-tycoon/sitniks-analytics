"""«Людський» темп відповіді агента — щоб діалог не виглядав роботизованим.

Реальна людина спершу читає повідомлення, потім набирає відповідь на телефоні — на це
йде час. Тому перед відправкою робимо паузу ~15 с (налаштовується) з невеликою
випадковістю, щоб затримка не була щоразу однаковою.
"""
from __future__ import annotations

import asyncio
import random

from src.config import settings


def reply_delay_seconds() -> float:
    """Скільки секунд «думати/друкувати» перед відповіддю (± ~30% випадковості)."""
    base = settings.AGENT_REPLY_DELAY_SECONDS
    if base <= 0:
        return 0.0
    return round(random.uniform(base * 0.7, base * 1.3), 1)


async def human_pause() -> float:
    """Асинхронна пауза перед відповіддю. Повертає фактичну затримку (для логів/тестів)."""
    d = reply_delay_seconds()
    if d > 0:
        await asyncio.sleep(d)
    return d
