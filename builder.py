# builder.py
from __future__ import annotations

from typing import Dict, List

import diff_ops


def apply_op(tokens: list[str], op: dict) -> None:
    """
    Применение одной операции к плоскому списку токенов.
    Здесь удаление физическое (не "del"-пометки), т.к. это проверка инварианта.
    """
    d = op.get("d")
    v = op.get("v")

    # примечание: ничего не меняет
    if d is None and v is None:
        return

    i = op["i"]
    delete_n = d or 0
    insert_v = v or []

    tokens[i:i + delete_n] = list(insert_v)


def find_first_mismatch(a: list[str], b: list[str]) -> int | None:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    if len(a) != len(b):
        return n
    return None


def validate_graph_tdj(
    *,
    versions: list[dict],
    edges: list[dict],
    context: int = 25
) -> None:
    """
    Проверяет инвариант графового TDJ:

      применение edge.ops к versions[edge.from].text
      даёт ровно versions[edge.to].text

    Плюс проверяет, что from/to существуют.
    """
    by_id = {v["id"]: v for v in versions}

    for ei, e in enumerate(edges):
        frm = e["from"]
        to = e["to"]

        if frm not in by_id:
            raise AssertionError(f"Edge[{ei}] references missing from-version id={frm!r}")
        if to not in by_id:
            raise AssertionError(f"Edge[{ei}] references missing to-version id={to!r}")

        cur = list(by_id[frm]["text"])
        for op in (e.get("ops") or []):
            apply_op(cur, op)

        expected = by_id[to]["text"]
        if cur != expected:
            mismatch = find_first_mismatch(cur, expected)

            msg = [
                f"TDJ invariant failed on edge {frm} -> {to}",
                f"edge_index={ei} ops_count={len(e.get('ops') or [])}",
                f"result_len={len(cur)} expected_len={len(expected)}",
            ]

            if mismatch is not None:
                a0 = max(0, mismatch - context)
                a1 = min(len(cur), mismatch + context)
                b0 = max(0, mismatch - context)
                b1 = min(len(expected), mismatch + context)

                msg += [
                    f"first mismatch at token index i={mismatch}",
                    f"result[{a0}:{a1}]: {cur[a0:a1]}",
                    f"expect[{b0}:{b1}]: {expected[b0:b1]}",
                ]

            raise AssertionError("\n".join(msg))


def build_tdj(*, meta: dict, versions: list[dict], validate: bool = True) -> dict:
    """
    Собирает ГРАФОВЫЙ TDJ:

      {
        "meta": {...},
        "versions": [...],
        "edges": [
          {"from": parentId, "to": childId, "ops": [...]},
          ...
        ]
      }

    Входные versions: список словарей из pipeline.py:
      {id,title,date,ts,src,note,parent?, raw}

    parent — один (дерево/лес), merge-родителей пока нет.
    """
    out_versions: list[dict] = []
    tokenized: Dict[str, List[str]] = {}

    # 1) tokenization + versions[]
    for v in versions:
        vid = v["id"]
        toks = diff_ops.tokenize(v["raw"])
        tokenized[vid] = toks

        out_versions.append({
            "id": v["id"],
            "title": v["title"],
            "date": v["date"],
            "ts": v["ts"],
            "src": v["src"],
            "note": v.get("note", ""),
            "parent": v.get("parent"),
            "text": toks,
        })

    # 2) edges[] from parent pointers (в порядке manifest)
    edges: list[dict] = []
    for v in versions:
        child_id = v["id"]
        parent_id = v.get("parent")

        if not parent_id:
            continue

        if parent_id not in tokenized:
            raise ValueError(
                f"Version {child_id!r} references missing parent {parent_id!r}. "
                f"Check manifest.yml ordering / ids."
            )

        ops = diff_ops.make_ops(
            tokenized[parent_id],
            tokenized[child_id]
        )

        edges.append({
            "from": parent_id,
            "to": child_id,
            "ops": ops,
        })

    tdj = {
        "meta": {
            "work": meta["work"],
            "part": meta["part"],
            "src": meta["src"],
            "note": meta["note"],
            "para": diff_ops.PARA_TOKEN,
        },
        "versions": out_versions,
        "edges": edges,
    }

    if validate:
        validate_graph_tdj(versions=out_versions, edges=edges)

    return tdj