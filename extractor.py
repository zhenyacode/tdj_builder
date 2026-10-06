# extractor.py
import re


PARA_SPLIT_RE = re.compile(r"\n\s*\n+", re.UNICODE)


def extract(text: str) -> dict:
    """
    Вход: сырой txt (строка) с фигурной разметкой:
      {+ins} {-del} {-old|+new}

    Выход:
      {
        "snapshots": [base_text] или [base_text, revised_text]
      }

    Где base_text/revised_text — обычные строки с нормализованными
    границами абзацев: '\n\n'.
    """
    text = normalize_input_text(text)

    paragraphs = split_paragraphs(text)

    base_paragraphs: list[str] = []
    revised_paragraphs: list[str] = []
    has_revisions = False

    for paragraph_index, paragraph in enumerate(paragraphs):
        validate_markup_paragraph(paragraph, paragraph_index)

        parsed = parse_paragraph(paragraph, paragraph_index)

        base_paragraphs.append(parsed["base"])
        revised_paragraphs.append(parsed["revised"])

        if parsed["base"] != parsed["revised"]:
            has_revisions = True

    base_text = "\n\n".join(base_paragraphs).strip()
    snapshots = [base_text]

    if has_revisions:
        revised_text = "\n\n".join(revised_paragraphs).strip()
        snapshots.append(revised_text)

    return {"snapshots": snapshots}


def normalize_input_text(text: str) -> str:
    # единые переводы строк + NBSP -> space
    return (
        text.replace("\r\n", "\n")
            .replace("\r", "\n")
            .replace("\u00a0", " ")
    )


def split_paragraphs(text: str) -> list[str]:
    # Абзац = блок между пустыми строками.
    # Внутренние одиночные '\n' внутри абзаца сохраняются.
    parts = PARA_SPLIT_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def validate_markup_paragraph(paragraph: str, paragraph_index: int) -> None:
    """
    Проверяет:
      - нет вложенных {...{...}...}
      - нет лишней закрывающей }
      - каждая {...} конструкция валидна по формату
      - фигурная разметка не пересекает границы абзаца (обеспечивается тем,
        что мы валидируем ПОСЛЕ split_paragraphs)
    """
    depth = 0
    opening_pos = None

    def quote(pos: int, before: int = 30, after: int = 80) -> str:
        start = max(0, pos - before)
        end = min(len(paragraph), pos + after)
        fragment = paragraph[start:end].replace("\n", " ")
        if start > 0:
            fragment = "…" + fragment
        if end < len(paragraph):
            fragment += "…"
        return fragment

    for pos, char in enumerate(paragraph):
        if char == "{":
            if depth != 0:
                raise ValueError(
                    f"Вложенная фигурная разметка в абзаце {paragraph_index + 1} не поддерживается.\n"
                    f"Фрагмент: «{quote(pos)}»"
                )
            depth = 1
            opening_pos = pos

        elif char == "}":
            if depth == 0:
                raise ValueError(
                    f"Закрывающая фигурная скобка без открывающей в абзаце {paragraph_index + 1}.\n"
                    f"Фрагмент: «{quote(pos)}»"
                )

            raw = paragraph[opening_pos:pos + 1]
            validate_brace(raw, paragraph_index, opening_pos)

            depth = 0
            opening_pos = None

    if depth:
        raise ValueError(
            f"Фигурная разметка в абзаце {paragraph_index + 1} не закрыта. "
            f"Правка не может пересекать границу абзаца.\n"
            f"Начало правки: «{quote(opening_pos, before=0)}»"
        )


def validate_brace(raw: str, paragraph_index: int, char_pos: int) -> None:
    """
    Допустимые конструкции:
        {+text}
        {-text}
        {-old|+new}
    """
    content = raw[1:-1]

    if not content:
        raise ValueError(
            f"Пустая фигурная конструкция в абзаце {paragraph_index + 1}, символ {char_pos}:\n{raw}"
        )

    # Вставка
    if content.startswith("+"):
        if "|" in content:
            raise ValueError(
                f"Некорректная вставка в абзаце {paragraph_index + 1}, символ {char_pos}.\n"
                f"Ожидается формат {{+текст}}:\n{raw}"
            )
        if not content[1:]:
            raise ValueError(
                f"Пустая вставка в абзаце {paragraph_index + 1}, символ {char_pos}:\n{raw}"
            )
        return

    # Удаление или замена
    if content.startswith("-"):
        parts = content.split("|")

        # Простое удаление
        if len(parts) == 1:
            if not parts[0][1:]:
                raise ValueError(
                    f"Пустое удаление в абзаце {paragraph_index + 1}, символ {char_pos}:\n{raw}"
                )
            return

        # Замена: {-old|+new}
        if (
            len(parts) == 2
            and parts[0].startswith("-")
            and parts[1].startswith("+")
            and parts[0][1:]
            and parts[1][1:]
        ):
            return

        raise ValueError(
            f"Некорректная замена в абзаце {paragraph_index + 1}, символ {char_pos}.\n"
            f"Разрешён только формат {{-старое|+новое}}:\n{raw}"
        )

    raise ValueError(
        f"Неизвестная фигурная конструкция в абзаце {paragraph_index + 1}, символ {char_pos}.\n"
        f"Разрешены {{+...}}, {{-...}}, {{-...|+...}}:\n{raw}"
    )


def parse_paragraph(paragraph: str, paragraph_index: int) -> dict:
    """
    Разворачивает фигурную разметку в два текста:
      base    — как было до правки
      revised — как стало после правки
    """
    base_parts: list[str] = []
    revised_parts: list[str] = []

    pos = 0

    for match in re.finditer(r"\{[^{}]*\}", paragraph):
        plain = paragraph[pos:match.start()]
        base_parts.append(plain)
        revised_parts.append(plain)

        raw = match.group(0)
        content = raw[1:-1]

        # Вставка: только в revised
        if content.startswith("+"):
            revised_parts.append(content[1:])

        # Удаление: только в base
        elif content.startswith("-") and "|" not in content:
            base_parts.append(content[1:])

        # Замена: {-old|+new}
        else:
            old, new = content.split("|", 1)
            base_parts.append(old[1:])
            revised_parts.append(new[1:])

        pos = match.end()

    tail = paragraph[pos:]
    base_parts.append(tail)
    revised_parts.append(tail)

    return {
        "base": "".join(base_parts),
        "revised": "".join(revised_parts),
    }