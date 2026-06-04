"""Класифікувати вже проаналізовані діалоги за дату — додати dialog_quality."""
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anthropic import AsyncAnthropic
from src.config import settings
from src.database.supabase_client import get_client

CLASSIFY_PROMPT = """Маєш короткі дані про діалог менеджера з клієнтом у косметичному магазині:
- Замовлення оформлене: {has_order}
- Загальна оцінка: {overall_score}/10
- Бали по критеріях: {scores}
- Резюме: {summary}

Класифікуй цей діалог:
- "good" = хороший приклад для навчання (замовлення + якісна консультація АБО видатна робота навіть без замовлення)
- "bad" = поганий приклад, для розбору (втрачений теплий клієнт, низька експертність, ігнор, грубість, не закрив угоду)
- "neutral" = звичайний робочий діалог (більшість)

Поверни ТІЛЬКИ валідний JSON:
{{"dialog_quality": "good|bad|neutral", "quality_reason": "коротке речення обґрунтування"}}"""


async def classify(client, record):
    scores_short = {k: (v.get("score") if isinstance(v, dict) else v) for k, v in (record.get("scores") or {}).items()}
    prompt = CLASSIFY_PROMPT.format(
        has_order=record.get("has_order"),
        overall_score=record.get("overall_score"),
        scores=json.dumps(scores_short, ensure_ascii=False),
        summary=(record.get("summary") or "")[:300],
    )
    resp = await client.messages.create(
        model="claude-haiku-4-5",  # дешева модель для класифікації
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()
    return json.loads(text)


async def main(date_str: str):
    cl = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    sb = get_client()

    res = sb.table("dialog_analyses").select("*").eq("dialog_date", date_str).not_.is_("overall_score", "null").execute()
    print(f"Записів за {date_str}: {len(res.data)}")

    # Підтягнемо chatId-и з замовленнями щоб правильно проставити has_order
    from src.sitniks.client import SitniksClient
    from datetime import datetime
    sc = SitniksClient()
    start = datetime.fromisoformat(f"{date_str}T00:00:00+03:00")
    end = datetime.fromisoformat(f"{date_str}T23:59:59+03:00")
    orders = await sc.get_orders(start, end)
    await sc.close()
    chat_ids_with_order = {o["chatId"] for o in orders if o.get("chatId")}
    print(f"chatIds з замовленням: {len(chat_ids_with_order)}")

    g, b, n, fails = 0, 0, 0, 0
    for i, rec in enumerate(res.data, 1):
        rec["has_order"] = rec["dialog_id"] in chat_ids_with_order
        try:
            result = await classify(cl, rec)
            q = result.get("dialog_quality")
            r = result.get("quality_reason", "")
            if q not in ("good", "bad", "neutral"):
                q = "neutral"
            sb.table("dialog_analyses").update({"dialog_quality": q, "quality_reason": r}).eq("dialog_id", rec["dialog_id"]).execute()
            if q == "good": g += 1
            elif q == "bad": b += 1
            else: n += 1
            if i % 10 == 0:
                print(f"  [{i}/{len(res.data)}] good={g} bad={b} neutral={n} fails={fails}")
        except Exception as e:
            fails += 1
            print(f"  ❌ {rec['dialog_id']}: {e}")
        await asyncio.sleep(0.3)

    print(f"\n✅ good={g} bad={b} neutral={n} fails={fails}")


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-06-03"
    asyncio.run(main(date))
