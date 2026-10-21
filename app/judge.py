"""Decide right or wrong for a question by comparing the student's answer with the key.

Claude only reads the answers off the page; the verdict is made here, so the same pair
of answers always gets the same result ('June 13' vs '13 June', 'C people would…' vs 'C').
"""
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, Sequence

from app.models import BLANK, CORRECT, OPTION_KINDS, UNANSWERED, UNGRADED, WRONG

BLANK_MARKS = {"", "-", "--", "—", "–", "_", "?", "未作答", "(未作答)", "未答", "无", "無", "空白", "n/a"}
TFNG = {
    "t": "TRUE", "true": "TRUE", "f": "FALSE", "false": "FALSE",
    "y": "YES", "yes": "YES", "n": "NO", "no": "NO",
    "ng": "NOT GIVEN", "n.g": "NOT GIVEN", "not given": "NOT GIVEN", "notgiven": "NOT GIVEN",
}
MONTHS = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april", "may": "may", "jun": "june",
    "jul": "july", "aug": "august", "sep": "september", "sept": "september", "oct": "october",
    "nov": "november", "dec": "december",
}
_MONTH = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_DAY_MONTH = re.compile(rf"^(\d{{1,2}})(?:st|nd|rd|th)?(?: of)? {_MONTH}$")
_MONTH_DAY = re.compile(rf"^{_MONTH} (\d{{1,2}})(?:st|nd|rd|th)?$")
# "C   people would…", "A. competitors", "(B)", "b"
_LETTER = re.compile(r"^\(?([A-Za-z])\)?(?:[.、:)\]]\s*|\s+|$)(.*)$", re.S)
_LETTER_LIST = re.compile(r"^[A-Za-z](?:\s*[,、&;和]\s*[A-Za-z]|\s+and\s+[A-Za-z])+$")


def clean(value: str) -> str:
    """Full-width to half-width, collapse spaces; blank marks like '未作答' or '-' become ''."""
    s = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value or "")).strip()
    return "" if s.lower() in BLANK_MARKS else s


def norm(value: str) -> str:
    """Comparison form: case, punctuation, 5.30 = 5:30, 1,000 = 1000, 13th June = June 13."""
    s = clean(value).lower().strip(" .,;:!?'\"“”‘’")
    s = re.sub(r"(\d{1,2})[.:](\d{2})\b", r"\1:\2", s)
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    s = re.sub(r"\s*-\s*", "-", s)
    m = _DAY_MONTH.match(s) or _MONTH_DAY.match(s)
    if m:
        day, month = (m.group(1), m.group(2)) if m.re is _DAY_MONTH else (m.group(2), m.group(1))
        s = f"{int(day)} {MONTHS[month[:4] if month.startswith('sept') else month[:3]]}"
    return s


def alternatives(key: str) -> list[str]:
    """'theater/theatre' -> both; '(the) leaflet(s)' -> with and without the bracketed part."""
    out: list[str] = []
    for part in clean(key).split("/"):
        pieces = re.split(r"\(([^)]*)\)", part.strip())  # text, optional, text, optional, ...
        optional = pieces[1::2][:4]
        for mask in range(2 ** len(optional)):
            kept = iter(opt if mask >> i & 1 else "" for i, opt in enumerate(optional))
            text = "".join(p if i % 2 == 0 else next(kept, "") for i, p in enumerate(pieces))
            out.append(re.sub(r"\s+", " ", text).strip())
    return list(dict.fromkeys(x for x in out if x))


def to_letter(answer: str, options: dict) -> Optional[str]:
    """The option letter an answer refers to, or None if it can't be told."""
    s = clean(answer)
    if not s:
        return ""
    n = norm(s)
    for letter, text in options.items():
        if text and norm(text) == n:
            return letter
    m = _LETTER.match(s)
    if m:
        letter, rest = m.group(1), m.group(2).strip()
        if not rest:
            return letter.upper()
        if letter.isupper():  # the letter shown next to the text is what was chosen
            return letter
    hits = [letter for letter, text in options.items() if text and (n in norm(text) or norm(text) in n)]
    return hits[0] if len(hits) == 1 else None


def _tfng(value: str) -> Optional[str]:
    return TFNG.get(norm(value)) or (clean(value).upper() if clean(value).upper() in TFNG.values() else None)


def canon(kind: str, value: str, options: dict) -> str:
    """How an answer is stored: a letter for option kinds, a full word for tfng, else as written."""
    s = clean(value)
    if not s:
        return ""
    if kind in OPTION_KINDS:
        return to_letter(s, options) or s
    if kind == "tfng":
        return _tfng(s) or s
    return s


def split_key(kind: str, key: str, options: dict) -> list[str]:
    """Answer key text -> list of accepted answers."""
    s = clean(key)
    if not s:
        return []
    if kind in OPTION_KINDS and _LETTER_LIST.match(s):
        parts = re.findall(r"(?<![A-Za-z])[A-Za-z](?![A-Za-z])", s)
    else:
        parts = s.split("/")
    out = [canon(kind, p, options) if kind != "fill" else clean(p) for p in parts]
    return list(dict.fromkeys(x for x in out if x))


def judge(kind: str, user: str, accepted: Sequence[str], options: dict) -> str:
    u = clean(user)
    if not u:
        return BLANK
    if not accepted:
        return UNGRADED
    if kind in OPTION_KINDS:
        keys = {norm(to_letter(k, options) or k) for k in accepted}
        return CORRECT if norm(to_letter(u, options) or u) in keys else WRONG
    if kind == "tfng" or all(_tfng(k) for k in accepted):
        return CORRECT if (_tfng(u) or u.upper()) in {_tfng(k) or k.upper() for k in accepted} else WRONG
    nu = norm(u)
    return CORRECT if any(nu == norm(alt) for k in accepted for alt in alternatives(k)) else WRONG


def judge_group(answers: Sequence[tuple[str, Sequence[str]]], options: dict) -> list[str]:
    """Choose-TWO style sets: each correct letter counts once, in any order."""
    pool = list(dict.fromkeys(
        norm(to_letter(k, options) or k) for _, accepted in answers for k in accepted))
    left = list(pool)
    out = []
    for user, _ in answers:
        u = norm(to_letter(user, options) or user) if clean(user) else ""
        if not u:
            out.append(BLANK)
        elif not pool:
            out.append(UNGRADED)
        elif u in left:
            left.remove(u)
            out.append(CORRECT)
        else:
            out.append(WRONG)
    return out


def _plural_pair(a: str, b: str) -> bool:
    a, b = sorted((a, b), key=len)
    return a != b and (b in (a + "s", a + "es") or (a.endswith("y") and b == a[:-1] + "ies"))


def guess_error_type(kind: str, user: str, accepted: Sequence[str]) -> Optional[str]:
    """Error types that can be told from the strings alone; None means ask Claude's opinion."""
    if not clean(user):
        return UNANSWERED
    if kind == "tfng":
        pair = {_tfng(user)} | {_tfng(k) for k in accepted}
        return "NOT GIVEN/FALSE 混淆" if "NOT GIVEN" in pair and pair & {"FALSE", "NO"} else None
    if kind != "fill":
        return None
    nu = norm(user)
    alts = [norm(a) for k in accepted for a in alternatives(k)]
    if any(_plural_pair(nu, a) for a in alts):
        return "單複數/詞形"
    if any(len(a) >= 4 and SequenceMatcher(None, nu, a).ratio() >= 0.75 for a in alts):
        return "拼字錯誤"
    if re.search(r"\d", nu) or any(re.search(r"\d", a) for a in alts):
        return "數字/日期"
    return None
