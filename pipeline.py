#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
import sys

import yaml

from extractor import extract
from builder import build_tdj


ROOT = Path(__file__).parent
TXT_DIR = ROOT / "txts"
MANIFEST_PATH = ROOT / "manifest.yml"


def pick_layer(snapshots: list[str], layer: str | None, ctx: str) -> str:
    if layer is None or layer == "base":
        return snapshots[0]
    if layer == "revised":
        if len(snapshots) < 2:
            raise ValueError(f"{ctx}: layer=revised, но extractor вернул только 1 снапшот")
        return snapshots[1]
    raise ValueError(f"{ctx}: неизвестный layer={layer!r} (ожидается base|revised или отсутствие поля)")


def main():
    manifest = validate(MANIFEST_PATH, TXT_DIR)

    meta = manifest["meta"]
    version_specs = manifest["versions"]

    # кэш: файл -> snapshots из extractor
    cache: dict[str, list[str]] = {}

    resolved_versions = []
    for v in version_specs:
        file_name = str(v["file"])
        path = TXT_DIR / file_name
        ctx = f"{v.get('id','?')} @ {file_name}"

        if file_name not in cache:
            text = path.read_text(encoding="utf-8")
            res = extract(text)
            cache[file_name] = res["snapshots"]

        raw_text = pick_layer(cache[file_name], v.get("layer"), ctx)

        resolved_versions.append({
            # поля TDJ
            "id": str(v["id"]),
            "title": str(v["title"]),
            "date": str(v["date_raw"]),
            "ts": str(v["date_tech"]),
            "src": str(v["src"]),
            "note": str(v.get("note", "")),
            # доп. мета для будущего графа (плеер пока не использует)
            "parent": str(v["parent"]) if v.get("parent") is not None else None,
            # raw текст версии
            "raw": raw_text,
        })

    tdj = build_tdj(meta=meta, versions=resolved_versions)

    out_path = ROOT / "tdj-text.json"
    out_path.write_text(json.dumps(tdj, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote:", out_path)


def validate(manifest_path: Path, txt_dir: Path) -> dict:
    """
    Проверяет структуру проекта и manifest.yml.
    Возвращает загруженный manifest.

    Ошибки прерывают сборку (ValueError).
    Лишние файлы в txts/ вызывают только предупреждение.
    """

    # 1. Проверяем наличие манифеста и папки txts
    if not manifest_path.is_file():
        raise ValueError(
            f"Ошибка: файл '{manifest_path.name}' не найден."
        )

    if not txt_dir.is_dir():
        raise ValueError(
            f"Ошибка: папка '{txt_dir.name}/' не найдена."
        )

    # 2. Загружаем YAML
    try:
        manifest = yaml.safe_load(
            manifest_path.read_text(encoding="utf-8")
        )
    except yaml.YAMLError as e:
        raise ValueError(
            f"Ошибка: не удалось прочитать manifest.yml.\n{e}"
        ) from e

    if not isinstance(manifest, dict):
        raise ValueError(
            "Ошибка: manifest.yml должен содержать YAML-объект."
        )

    # 3. Проверяем наличие основных секций
    for section in ("meta", "versions"):
        if section not in manifest:
            raise ValueError(
                f"Ошибка: в manifest.yml отсутствует секция '{section}'."
            )

    meta = manifest["meta"]
    versions = manifest["versions"]

    if not isinstance(meta, dict):
        raise ValueError(
            "Ошибка: секция 'meta' должна быть YAML-объектом."
        )

    if not isinstance(versions, list) or not versions:
        raise ValueError(
            "Ошибка: секция 'versions' должна содержать непустой список версий."
        )

    # 4. Обязательные поля метаданных (note может быть пустым)
    for field in ("work", "part", "src"):
        if not str(meta.get(field, "")).strip():
            raise ValueError(
                f"Ошибка: в секции 'meta' отсутствует или пустое обязательное поле '{field}'."
            )
    if "note" not in meta:
        raise ValueError("Ошибка: в секции 'meta' отсутствует обязательное поле 'note'.")

    # 5. Обязательные поля версий + уникальность ID
    required_fields = ("id", "file", "title", "date_raw", "date_tech", "src")
    ids = set()

    for index, version in enumerate(versions, start=1):
        if not isinstance(version, dict):
            raise ValueError(
                f"Ошибка: версия №{index} должна быть YAML-объектом."
            )

        for field in required_fields:
            val = version.get(field)
            if val is None or not str(val).strip():
                raise ValueError(
                    f"Ошибка: у версии №{index} отсутствует или пустое обязательное поле '{field}'."
                )

        vid = str(version["id"]).strip()

        if vid in ids:
            raise ValueError(
                f"Ошибка: ID версии '{vid}' повторяется несколько раз. ID должны быть уникальными."
            )

        ids.add(vid)

    # 6. Проверяем файлы и родителей
    used_files = set()
    parents = {}

    for version in versions:
        vid = str(version["id"]).strip()
        filename = str(version["file"]).strip()

        used_files.add(filename)

        if not (txt_dir / filename).is_file():
            raise ValueError(
                f"Ошибка: файл '{filename}' для версии '{vid}' не найден в папке txts/."
            )

        parent = version.get("parent")

        if parent is not None:
            parent_str = str(parent).strip()
            if not parent_str:
                raise ValueError(
                    f"Ошибка: некорректный parent у версии '{vid}'."
                )

            if parent_str == vid:
                raise ValueError(
                    f"Ошибка: версия '{vid}' не может ссылаться сама на себя."
                )

            if parent_str not in ids:
                raise ValueError(
                    f"Ошибка: версия '{vid}' ссылается на несуществующего родителя '{parent_str}'."
                )
            parents[vid] = parent_str
        else:
            parents[vid] = None

    # 7. Проверяем отсутствие циклов
    checked = set()

    for vid in ids:
        if vid in checked:
            continue

        path = []
        positions = {}
        current = vid

        while current is not None and current not in checked:
            if current in positions:
                cycle = path[positions[current]:] + [current]
                raise ValueError(
                    "Ошибка: обнаружен цикл в связях версий: "
                    + " → ".join(cycle)
                )

            positions[current] = len(path)
            path.append(current)
            current = parents[current]

        checked.update(path)

    # 8. Предупреждаем о лишних файлах (игнорируя скрытые и папки)
    for path in sorted(txt_dir.iterdir()):
        if path.is_file() and not path.name.startswith(".") and path.name not in used_files:
            print(
                f"Предупреждение: файл '{path.name}' в папке txts/ "
                "не упомянут в манифесте и будет проигнорирован."
            )

    return manifest


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        print(f"\n{e}\n")
        sys.exit(1)