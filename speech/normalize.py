"""Spoken-number and phonetic-alphabet normalisation for radio transcripts.

Lexer output is a list of atomic tokens:
  * a single digit character ``"0"``-``"9"`` (from digit words or digit strings)
  * an upper-case single letter (from the phonetic alphabet or letter strings)
  * ``"20"``-style tens/teens words are kept as words (``"seventy"``) and resolved by
    :func:`collapse_run`
  * ``","`` / ``"."`` boundary tokens
  * any other lower-case word
"""

from __future__ import annotations

import re

DIGIT_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "niner": "9", "tree": "3",
    "fife": "5", "fower": "4", "won": "1",
}
TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
ORDINAL_UNITS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
                 "seventh": 7, "eighth": 8, "ninth": 9}
PHONETIC = {
    "alpha": "A", "alfa": "A", "bravo": "B", "charlie": "C", "delta": "D", "echo": "E",
    "foxtrot": "F", "golf": "G", "hotel": "H", "india": "I", "juliet": "J", "juliett": "J",
    "kilo": "K", "lima": "L", "mike": "M", "november": "N", "oscar": "O", "papa": "P",
    "quebec": "Q", "romeo": "R", "sierra": "S", "tango": "T", "uniform": "U", "victor": "V",
    "whiskey": "W", "whisky": "W", "xray": "X", "yankee": "Y", "zulu": "Z",
}
LETTER_TO_PHONETIC = {
    "A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo", "F": "Foxtrot",
    "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliet", "K": "Kilo", "L": "Lima",
    "M": "Mike", "N": "November", "O": "Oscar", "P": "Papa", "Q": "Quebec", "R": "Romeo",
    "S": "Sierra", "T": "Tango", "U": "Uniform", "V": "Victor", "W": "Whiskey",
    "X": "X-Ray", "Y": "Yankee", "Z": "Zulu",
}
DIGIT_TO_WORD = {"0": "Zero", "1": "One", "2": "Two", "3": "Three", "4": "Four", "5": "Five",
                 "6": "Six", "7": "Seven", "8": "Eight", "9": "Niner"}
WORD_ALIASES = {"medivac": "medevac", "medevack": "medevac", "medavac": "medevac",
                "mayday": "mayday", "squawking": "squawk"}
MULTIPLIERS = {"hundred", "thousand"}


def _is_numeric_token(t: str) -> bool:
    return t in TEENS or t in TENS or t in MULTIPLIERS or (len(t) == 1 and t.isdigit())


def is_letter_token(t: str) -> bool:
    return len(t) == 1 and t.isupper()


def lex(text: str) -> list[str]:
    """Tokenise radio text into the atomic tokens described in the module docstring."""
    s = text.replace("’", "'")
    s = re.sub(r"(?i)\bx[\s-]?ray\b", "xray", s)
    s = re.sub(r"(?i)\bi\.?\s?m\.?\s?c\b", "imc", s)
    s = re.sub(r"(?i)\bv\.?\s?f\.?\s?r\b", "vfr", s)
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    s = re.sub(r"(?i)\bpan[\s-]+pan\b", "panpan", s)
    s = re.sub(r"(?i)\bmay[\s-]+day\b", "mayday", s)
    s = re.sub(r"(?i)\b(\d+)(?:st|nd|rd|th)\b", r"\1", s)
    out: list[str] = []
    for m in re.finditer(r"[A-Za-z]+|\d+|[,.;?!]", s):
        w = m.group(0)
        if w[0].isdigit():
            out.extend(w)
            continue
        if w in ",.;?!":
            out.append(",")
            continue
        wl = w.lower()
        wl = WORD_ALIASES.get(wl, wl)
        if wl in DIGIT_WORDS:
            out.append(DIGIT_WORDS[wl])
        elif wl in PHONETIC:
            out.append(PHONETIC[wl])
        elif len(w) == 1 and wl not in {"a", "i"}:
            out.append(w.upper())
        else:
            out.append(wl)
    return out


def collapse_run(run: list[str]) -> str:
    """Collapse a run of numeric tokens to its written form.

    With ``hundred``/``thousand`` present: arithmetic ("one thousand five hundred" -> 1500,
    "fifteen hundred" -> 1500). Otherwise concatenate ("two six four six" -> 2646).
    """
    if any(t in MULTIPLIERS for t in run):
        total, cur = 0, 0
        for t in run:
            if t.isdigit():
                cur += int(t)
            elif t in TEENS:
                cur += TEENS[t]
            elif t in TENS:
                cur += TENS[t]
            elif t == "hundred":
                cur = (cur or 1) * 100
            elif t == "thousand":
                total += (cur or 1) * 1000
                cur = 0
        return str(total + cur)
    parts: list[str] = []
    i = 0
    while i < len(run):
        t = run[i]
        if t in TENS and i + 1 < len(run) and run[i + 1].isdigit() and run[i + 1] != "0":
            parts.append(str(TENS[t] + int(run[i + 1])))
            i += 2
            continue
        if t in TEENS:
            parts.append(str(TEENS[t]))
        elif t in TENS:
            parts.append(str(TENS[t]))
        else:
            parts.append(t)
        i += 1
    return "".join(parts)


def group_runs(tokens: list[str]) -> list[tuple[str, list[str]]]:
    """Group tokens into ("run", [...]) numeric/letter runs and ("word", [w]) singles.

    A run needs at least one numeric token, or two+ letter tokens; a lone letter stays a word.
    """
    out: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if _is_numeric_token(t) or is_letter_token(t):
            j = i
            while j < len(tokens) and (_is_numeric_token(tokens[j]) or is_letter_token(tokens[j])):
                j += 1
            run = tokens[i:j]
            has_num = any(_is_numeric_token(x) for x in run)
            if has_num or len(run) >= 2:
                out.append(("run", run))
            else:
                out.append(("word", [run[0].lower()]))
            i = j
        else:
            out.append(("word", [t]))
            i += 1
    return out


def collapse_mixed(toks: list[str]) -> str:
    """Collapse a mixed digit/letter run keeping order (e.g. 2 6 4 6 X -> '2646X')."""
    buf: list[str] = []
    cur: list[str] = []
    for t in toks:
        if is_letter_token(t):
            if cur:
                buf.append(collapse_run(cur))
                cur = []
            buf.append(t)
        else:
            cur.append(t)
    if cur:
        buf.append(collapse_run(cur))
    return "".join(buf)


def normalize_for_wer(text: str) -> str:
    """Canonical lower-case form used for WER: digit runs/phonetic runs collapsed."""
    parts: list[str] = []
    for kind, toks in group_runs(lex(text)):
        if kind == "run":
            parts.append(collapse_mixed(toks).lower())
        elif toks[0] != ",":
            parts.append(toks[0])
    return " ".join(parts)



def spell_callsign(norm: str) -> str:
    """'2646X' -> 'Two Six Four Six X-Ray' (spoken form)."""
    words = []
    for ch in norm:
        if ch.isdigit():
            words.append(DIGIT_TO_WORD[ch])
        elif ch.upper() in LETTER_TO_PHONETIC:
            words.append(LETTER_TO_PHONETIC[ch.upper()])
    return " ".join(words)
