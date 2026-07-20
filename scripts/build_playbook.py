"""Крок 2: будує плейбук продавця з РЕАЛЬНИХ good-діалогів → таблиця tone_of_voice.

Чому так: raw_dialog у БД порожній, тож вербатим-текст дотягуємо з Sitniks по dialog_id.
Claude витягує стиль (voice), winning_moves і objection_playbook кращих менеджерів.
Потім consultant/playbook.py підмішує це у промпт агента-продавця.

Ідемпотентний: dialog_id, які вже є в tone_of_voice, пропускає — можна доганяти партіями.

Запуск:
    source venv/bin/activate
    PYTHONPATH=. python scripts/build_playbook.py [N] [min_score]
        N          скільки топ good-діалогів обробити (за замовч. 30)
        min_score  мінімальний overall_score (0-10, за замовч. 7)
"""
from __future__ import annotations

import asyncio
import sys

from src.claude.llm import complete_json
from src.claude.sales_prompts import TONE_OF_VOICE_PROMPT
from src.database.supabase_client import _db, save_tone
from src.sitniks.client import SitniksClient
from src.sitniks.parser import format_dialog_for_claude

MAX_DIALOG_CHARS = 14000   # обрізаємо дуже довгі мультисесійні діалоги (контроль вартості)
MIN_MESSAGES = 8           # надто короткі діалоги нічого не навчать
CONCURRENCY = 3            # щоб не впертись у rate-limit Sitniks


async def _process(dlg: dict, sem: asyncio.Semaphore) -> dict | None:
    """Один good-діалог → рядок tone_of_voice (або None, якщо не вдалось/замало)."""
    dialog_id = dlg["dialog_id"]
    async with sem:
        client = SitniksClient()
        try:
            messages = await client.get_chat_messages(dialog_id)
        except Exception as e:
            print(f"  ✗ {dialog_id}: fetch failed — {e}", flush=True)
            return None
        finally:
            await client.close()

    if len(messages) < MIN_MESSAGES:
        print(f"  · {dialog_id}: замало повідомлень ({len(messages)}) — skip", flush=True)
        return None

    dialog_text = format_dialog_for_claude(messages)[:MAX_DIALOG_CHARS]
    try:
        extracted = await complete_json(
            TONE_OF_VOICE_PROMPT.format(dialog_text=dialog_text), max_tokens=3500
        )
    except Exception as e:
        print(f"  ✗ {dialog_id}: claude failed — {e}", flush=True)
        return None

    wins = extracted.get("winning_moves") or []
    objs = extracted.get("objection_playbook") or []
    row = {
        "manager_name": dlg.get("manager_name"),
        "dialog_id": dialog_id,
        "winning_moves": wins,
        "objection_playbook": objs,
        "voice": extracted.get("voice") or {},
    }
    try:
        save_tone(row)
    except Exception as e:
        print(f"  ✗ {dialog_id}: save failed — {e}", flush=True)
        return None
    print(f"  ✓ {dlg.get('manager_name')} [{dialog_id}] — {len(wins)} moves, {len(objs)} objections", flush=True)
    return row


async def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    min_score = float(sys.argv[2]) if len(sys.argv) > 2 else 7.0

    db = _db()
    done = {r["dialog_id"] for r in db.table("tone_of_voice").select("dialog_id").execute().data}
    good = (
        db.table("dialog_analyses")
        .select("dialog_id,manager_name,overall_score")
        .eq("dialog_quality", "good")
        .gte("overall_score", min_score)
        .order("overall_score", desc=True)
        .limit(n * 3)  # запас, бо частину відсіємо (короткі/вже оброблені)
        .execute()
        .data
    )
    todo = [d for d in good if d["dialog_id"] not in done][:n]
    print(f"good-діалогів (score≥{min_score}): {len(good)} · вже в плейбуку: {len(done)} · обробляємо: {len(todo)}")
    if not todo:
        print("Нема чого доганяти.")
        return

    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*[_process(d, sem) for d in todo])
    saved = [r for r in results if r]
    total_moves = sum(len(r["winning_moves"]) for r in saved)
    total_objs = sum(len(r["objection_playbook"]) for r in saved)
    print(f"\n✓ Збережено {len(saved)} діалогів → {total_moves} winning_moves, {total_objs} objection replies")


if __name__ == "__main__":
    asyncio.run(main())
