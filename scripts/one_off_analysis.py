"""Аналіз одного діалогу зі збереженням у Supabase — для перевірки end-to-end."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from src.analyzer.pipeline import analyze_period


async def main():
    today = datetime.now()
    yesterday = today - timedelta(days=1)

    # Беремо тільки 3 чати для тесту
    results = await analyze_period(yesterday, today, max_chats=3, concurrency=2)

    print("\n=== ПІДСУМОК ===")
    for r in results:
        print(f"{r['manager_name']:25} | {r['overall_score']}/10 | {r['summary'][:80]}")


asyncio.run(main())
