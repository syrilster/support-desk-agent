import re

_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)")

def redact(text: str, known_names: tuple = ()) -> str:
    for name in known_names:
        if name:
            text = re.sub(re.escape(name), "[NAME]", text, flags=re.I)
    text = _CARD.sub("[CARD]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    return _PHONE.sub("[PHONE]", text)