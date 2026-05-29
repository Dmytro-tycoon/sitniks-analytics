"""Масовий аналіз — для початкової вибірки та тестування звітів."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from src.analyzer.pipeline import analyze_period


async def main():
    today = datetime.now()
    yesterday = today - timedelta(days=1)

    # 20 чатів, паралельно 4 одночасно
    results = await analyze_period(yesterday, today, max_chats=20, concurrency=4)

    # Зведення по менеджерах
    from collections import defaultdict
    by_m = defaultdict(list)
    for r in results:
        by_m[r["manager_name"]].append(r["overall_score"])

    print("\n=== СЕРЕДНЯ ОЦІНКА ПО МЕНЕДЖЕРАХ ===")
    for m, scores in sorted(by_m.items(), key=lambda kv: -sum(kv[1])/len(kv[1])):
        print(f"{m:30} {sum(scores)/len(scores):.1f}/10  ({len(scores)} діалогів)")


asyncio.run(main())
