"""Запуск агента-продавця у Sitniks (Instagram-директ та інші джерела).

    python scripts/run_sitniks_seller.py

Потрібні ключі Sitniks + Claude. Агент відповідає в чатах, де клієнт чекає на відповідь.
"""
import asyncio

from src.channels.sitniks_seller import run

if __name__ == "__main__":
    asyncio.run(run())
