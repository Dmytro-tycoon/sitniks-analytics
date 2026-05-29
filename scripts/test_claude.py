import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.claude.client import ClaudeAnalyzer
from src.sitniks.parser import format_dialog_for_claude


async def main():
    with open("tests/fixtures/sample_dialogs.json", encoding="utf-8") as f:
        dialogs = json.load(f)

    dialog = dialogs[0]
    messages = dialog.get("messages", [])

    if not messages:
        print("Немає повідомлень у fixture. Запусти спочатку scripts/test_sitniks.py")
        return

    dialog_text = format_dialog_for_claude(messages)
    print("=== ДІАЛОГ ===")
    print(dialog_text[:500])
    print("...\n")

    analyzer = ClaudeAnalyzer()
    result = await analyzer.analyze_dialog(
        dialog_text=dialog_text,
        manager_name=dialog.get("assignedManagerName", "Невідомо"),
        chat_status=dialog.get("status", ""),
        started_at=dialog.get("createdAt", ""),
    )

    print("=== РЕЗУЛЬТАТ АНАЛІЗУ ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


asyncio.run(main())
