#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from pathlib import Path

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
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))

    meta = manifest["meta"]
    version_specs = manifest["versions"]

    # кэш: файл -> snapshots из extractor
    cache: dict[str, list[str]] = {}

    resolved_versions = []
    for v in version_specs:
        file_name = v["file"]
        path = TXT_DIR / file_name
        ctx = f"{v.get('id','?')} @ {file_name}"

        if file_name not in cache:
            text = path.read_text(encoding="utf-8")
            res = extract(text)
            cache[file_name] = res["snapshots"]

        raw_text = pick_layer(cache[file_name], v.get("layer"), ctx)

        resolved_versions.append({
            # поля TDJ
            "id": v["id"],
            "title": v["title"],
            "date": v["date_raw"],
            "ts": v["date_tech"],
            "src": v["src"],
            "note": v.get("note", ""),
            # доп. мета для будущего графа (плеер пока не использует)
            "parent": v.get("parent"),
            # raw текст версии
            "raw": raw_text,
        })

    tdj = build_tdj(meta=meta, versions=resolved_versions)

    out_path = ROOT / "txts.json"
    out_path.write_text(json.dumps(tdj, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote:", out_path)


if __name__ == "__main__":
    main()