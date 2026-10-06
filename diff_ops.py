import re
from difflib import SequenceMatcher

PARA_TOKEN = "\n\n"                       # то, что хранится в versions[].text
PARA_SPLIT_RE = re.compile(r"\n\s*\n+", re.UNICODE)
WS_RE = re.compile(r"\s+", re.UNICODE)

# Токены: ... / … / <Анна / слова с <...> / дефисные слова / одиночная пунктуация
TOKEN_RE = re.compile(
    r"\.{3}|…|"                                       # ... или …
    r"<[\w\u0300-\u036f]+|"                           # токен вида "<Анна"
    r"[\w\u0300-\u036f]+"                             # слово/число + комбинируемые знаки
    r"(?:<[^>\s]+>?)?"                                # опционально "<...>" или "<..." (без >)
    r"(?:[-‑][\w\u0300-\u036f]+(?:<[^>\s]+>?)?)*|"    # дефисные части (6-е, по-русски)
    r"[^\s]",                                         # любой прочий непробельный символ
    re.UNICODE
)


def tokenize(text: str) -> list[str]:
    """
    Токенизация документа в плоский список токенов.
    Между абзацами вставляется PARA_TOKEN = "\\n\\n".
    Пробелы не храним.
    """
    text = (
        text.replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\u00a0", " ")
            .strip()
    )
    if not text:
        return []

    paragraphs = [p.strip() for p in PARA_SPLIT_RE.split(text) if p.strip()]

    out: list[str] = []
    for k, p in enumerate(paragraphs):
        # внутри абзаца нормализуем whitespace (одиночные \n -> пробел)
        p = p.replace("\n", " ")
        p = WS_RE.sub(" ", p).strip()

        if p:
            out.extend(TOKEN_RE.findall(p))

        if k != len(paragraphs) - 1:
            out.append(PARA_TOKEN)

    return out


def make_ops(source_tokens: list[str], target_tokens: list[str]) -> list[dict]:
    """
    Делает ops в новом формате:
      { i, d?, v? }

    Важно: i — логический индекс среди "живых" токенов (как в визуализаторе).
    Поэтому i считается не напрямую из opcodes, а через курсор pos,
    который обновляется так же, как при применении ops.
    """
    sm = SequenceMatcher(a=source_tokens, b=target_tokens, autojunk=False)

    ops: list[dict] = []
    pos = 0  # логическая позиция в текущем тексте (после учёта предыдущих ops)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        src_len = i2 - i1
        tgt_seg = target_tokens[j1:j2]

        if tag == "equal":
            pos += src_len
            continue

        if tag == "delete":
            ops.append({"i": pos, "d": src_len})
            # pos не меняется
            continue

        if tag == "insert":
            ops.append({"i": pos, "v": tgt_seg})
            pos += len(tgt_seg)
            continue

        if tag == "replace":
            op = {"i": pos}
            if src_len:
                op["d"] = src_len
            if tgt_seg:
                op["v"] = tgt_seg
            ops.append(op)
            pos += len(tgt_seg)
            continue

        raise ValueError(f"Unknown opcode tag: {tag}")

    return ops


def make_diff_ops(source_text: str, target_text: str) -> dict:
    """
    Возвращает то, что нужно builder'у:
      - source_tokens / target_tokens (их можно класть в versions[].text)
      - ops (для tdj.ops)
    """
    source_tokens = tokenize(source_text)
    target_tokens = tokenize(target_text)

    ops = make_ops(source_tokens, target_tokens)

    return {
        "source_tokens": source_tokens,
        "target_tokens": target_tokens,
        "ops": ops,
    }