import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from src.sitniks.client import SitniksClient


async def main():
    client = SitniksClient()

    today = datetime.now()
    yesterday = today - timedelta(days=1)

    print(f"Отримую чати за {yesterday.date()} — {today.date()}...")
    chats = await client.get_all_chats(yesterday, today)
    print(f"Знайдено {len(chats)} чатів")

    if chats:
        first = chats[0]
        print(f"\nПриклад чату:")
        print(json.dumps(first, ensure_ascii=False, indent=2))

        print(f"\nОтримую повідомлення чату {first['id']}...")
        messages = await client.get_chat_messages(first["id"])
        print(f"Повідомлень: {len(messages)}")
        for m in messages[:3]:
            print(f"  [{m.get('managerName', 'клієнт')}]: {m.get('text', '')[:80]}")

        # Зберігаємо приклад для тестів
        sample = {**first, "messages": messages}
        os.makedirs("tests/fixtures", exist_ok=True)
        with open("tests/fixtures/sample_dialogs.json", "w", encoding="utf-8") as f:
            json.dump([sample], f, ensure_ascii=False, indent=2)
        print("\n✅ Приклад збережено в tests/fixtures/sample_dialogs.json")

    await client.close()


asyncio.run(main())
