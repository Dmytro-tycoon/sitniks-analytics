"""Евристичне виявлення спам/шахрайських Instagram-профілів."""
import re

# Маркери у назві профілю (case-insensitive)
SPAM_NAME_PATTERNS = [
    r"\bsupport\b",
    r"\bbusiness\b",
    r"\bchat\s*ai\b|\bai\s*chat\b",
    r"\bsupport\s*ai\b|\bai\s*support\b",
    r"\bassistant\b",
    r"\bhelp\s*desk\b|\bhelpdesk\b",
    r"\bcustomer\s*(care|service|support)\b",
    r"\b(crypto|bitcoin|btc|eth|usdt|invest|forex|trader|trading)\b",
    r"\bofficial\b.*\b(support|page)\b",
    r"\bverified\b",
    r"\b(claim|prize|winner|gift|reward)\b",
]

# Підозрілі суфікси у нікнеймі
SPAM_NICK_PATTERNS = [
    r"_?love\d*$",       # njn8love
    r"_?official\d*$",
    r"_?support\d*$",
    r"_?help\d*$",
    r"_?bot\d*$",
    r"^chat_?",
    r"^bot_?",
    r"^support_?",
    r"^ai_?",
]


def is_spam_profile(client_name: str = "", client_username: str = "") -> tuple[bool, str]:
    """
    Повертає (is_spam, reason).
    Перевіряє ім'я і нік на маркери шахраїв.
    """
    name = (client_name or "").strip().lower()
    nick = (client_username or "").strip().lower()

    for pat in SPAM_NAME_PATTERNS:
        if re.search(pat, name):
            return True, f"name pattern: {pat}"

    for pat in SPAM_NICK_PATTERNS:
        if re.search(pat, nick):
            return True, f"nick pattern: {pat}"

    return False, ""
