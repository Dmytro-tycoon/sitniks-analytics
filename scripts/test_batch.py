"""Тест batch-аналізу: 10 чатів, перевіряємо що batch працює end-to-end."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from src.analyzer.pipeline import analyze_period


async def main():
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    saved = await analyze_period(yesterday, today, max_chats=10)
    print(f"\n=== Saved: {saved} ===")


asyncio.run(main())
