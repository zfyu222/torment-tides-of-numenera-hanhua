"""Restore validated text layout and repair verified runtime markup changes."""

from __future__ import annotations

import csv
import difflib
import re
import subprocess
from io import StringIO
from pathlib import Path


TRANSLATION = Path("torment-tides-of-numenera_text_translated.csv")
BREAK_RE = re.compile(r"\r\n|\r|\n|\\n")
FIXES = {
    57_346: ("[FettleIcon: Phase]", "[FettleIcon: Status]"),
    57_747: ("为所有队伍成员治疗[/Color] [Gold]", "为所有队伍成员治疗 [Gold]"),
    62_267: ("（01）", "{01}"),
    62_268: ("（02）", "{02}"),
}


def load_csv(handle) -> list[list[str]]:
    return list(csv.reader(handle))


def layout(text: str) -> tuple[str, list[tuple[int, str]]]:
    parts, tokens = BREAK_RE.split(text), BREAK_RE.findall(text)
    position, layout_tokens = 0, []
    for part, token in zip(parts, tokens):
        position += len(part)
        layout_tokens.append((position, token))
    return "".join(parts), layout_tokens


def map_position(before: str, after: str, position: int) -> int:
    blocks = difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_matching_blocks()
    for block in blocks:
        if block.a <= position <= block.a + block.size:
            return block.b + position - block.a
    prior = [block for block in blocks if block.a + block.size <= position]
    following = [block for block in blocks if block.a >= position]
    if prior:
        return prior[-1].b + prior[-1].size
    if following:
        return following[0].b
    return min(position, len(after))


def restore_layout(previous: str, current: str) -> str:
    old_plain, old_layout = layout(previous)
    new_plain, current_layout = layout(current)
    if old_layout == current_layout:
        return current
    insertions: dict[int, list[str]] = {}
    for old_position, token in old_layout:
        insertions.setdefault(map_position(old_plain, new_plain, old_position), []).append(token)
    result = []
    for index, character in enumerate(new_plain):
        if index in insertions:
            result.extend(insertions[index])
        result.append(character)
    result.extend(insertions.get(len(new_plain), []))
    return "".join(result)


def main() -> int:
    previous_raw = subprocess.check_output(["git", "show", f"HEAD:{TRANSLATION.name}"])
    previous = load_csv(StringIO(previous_raw.decode("utf-8-sig"), newline=""))
    with TRANSLATION.open(encoding="utf-8-sig", newline="") as handle:
        current = load_csv(handle)
    if len(previous) != len(current):
        raise RuntimeError("Translation CSV logical row counts do not match")
    restored = 0
    for old_row, current_row in zip(previous, current):
        replacement = restore_layout(old_row[0], current_row[0])
        if replacement != current_row[0]:
            current_row[0] = replacement
            restored += 1
    for line, (old, new) in FIXES.items():
        value = current[line - 1][0]
        if value.count(old) != 1:
            raise RuntimeError(f"Expected exactly one repair target on line {line}")
        current[line - 1][0] = value.replace(old, new)
    with TRANSLATION.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(current)
    print(f"restored_layout_rows={restored}; repaired_runtime_markers={len(FIXES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
