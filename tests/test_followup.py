from datetime import datetime, timedelta, timezone

from src.followup.price_silent import classify, group_of, render, report_text

T0 = datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)  # 11:00 Київ


def msg(minutes, text, manager=False, attach=False):
    m = {"createdAt": (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
         "text": text, "messageScope": "standard", "attachments": ["x"] if attach else []}
    if manager:
        m["managerName"] = "Даша"
    return m


PRICE_CHAT = [
    msg(0, "Яка ціна?"),
    msg(2, "Вітаю 🤍", True),
    msg(3, "Крем з вітаміном К… 15 мл - 725 грн", True),
    msg(3, "", True, attach=True),
    msg(4, "Бажаєте спробувати?)", True),
]


def at(hours):
    return T0 + timedelta(hours=hours)


def test_candidate_in_window():
    v = classify(PRICE_CHAT, False, at(5))
    assert v.ok, v.reason


def test_too_early_and_too_late():
    assert classify(PRICE_CHAT, False, at(2)).reason == "ще рано (<3 год тиші)"
    assert classify(PRICE_CHAT, False, at(23)).reason == "вікно 22 год минуло"


def test_exclusions():
    assert classify(PRICE_CHAT, True, at(5)).reason == "має замовлення"
    assert not classify(PRICE_CHAT + [msg(10, "Ні, дякую")], False, at(5)).ok  # last from client
    refused = PRICE_CHAT[:1] + [msg(1, "Ні, дякую")] + PRICE_CHAT[1:]
    assert classify(refused, False, at(5)).reason == "відмова / «подумаю»"
    agreed = PRICE_CHAT + [msg(6, "Так, бажаю"), msg(7, "Як зручно оплатити?", True)]
    assert not classify(agreed, False, at(5)).ok
    flow = PRICE_CHAT + [msg(6, "Для вас сьогодні знижка 10% 😊", True)]
    assert classify(flow, False, at(5)).reason == "інший дотиск (−10% / реквізити)"
    no_price_q = [msg(0, "Хочу Догляд!")] + PRICE_CHAT[1:]
    assert classify(no_price_q, False, at(5)).reason == "не питала ціну"


def test_pdrn_percent_is_not_discount_flow():
    chat = PRICE_CHAT + [msg(5, "У складі: Полінуклеотиди (PDRN) 10% - колаген", True)]
    assert classify(chat, False, at(5)).ok


def test_texts_and_groups():
    assert render("кремом з вітаміном К", at(0), at(5)) == (
        "Добрий день! 🌿 Сьогодні ви цікавились кремом з вітаміном К. Хочете, підкажу, чи підійде цей засіб саме вам?")
    assert render(None, at(0), at(24)).startswith("Добрий день! 🌿 Вчора ви цікавились нашим доглядом.")
    assert group_of("abc") == group_of("abc") and group_of("abc") in ("A", "B")
    ids = [f"chat{i}" for i in range(400)]
    share = sum(group_of(i) == "A" for i in ids) / len(ids)
    assert 0.4 < share < 0.6


def test_report_text_shadow():
    stats = {"mode": "shadow", "checked": 3, "A": [{"client_name": "Іра", "manager": "Даша", "message": "Текст", "sent_ok": None}],
             "B": [{"client_name": "Оля"}], "errors": []}
    t = report_text(stats, at(2))
    assert "тіньовий режим" in t and "надіслав би" in t and "Оля" in t
