#!/usr/bin/env python3
"""Build a Chinese overlay for Torment's English .stringtable directory.

The game stores localization as XML files under StreamingAssets.  This script
copies the complete English locale tree, then replaces every non-empty
DefaultText/FemaleText value using the aligned source and translated CSV files.
It deliberately preserves the original XML layout instead of reserializing the
documents through ElementTree.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


TEXT_NODE = re.compile(
    r"<(DefaultText|FemaleText)>(.*?)</\1>",
    flags=re.DOTALL,
)
INVALID_XML_CHAR = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]"
)


def load_column(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if any(len(row) != 1 for row in rows):
        raise ValueError(f"{path.name} is not a single-column CSV")
    return [row[0] for row in rows]


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_csv", type=Path)
    parser.add_argument("translated_csv", type=Path)
    parser.add_argument("english_locale", type=Path)
    parser.add_argument("output_locale", type=Path)
    args = parser.parse_args()

    source = load_column(args.source_csv)
    translated = load_column(args.translated_csv)
    if len(source) != len(translated):
        raise ValueError(f"CSV record mismatch: {len(source)} != {len(translated)}")
    if args.output_locale.exists():
        raise FileExistsError(f"output already exists: {args.output_locale}")

    mapping: dict[str, str] = {}
    for original, replacement in zip(source, translated):
        key = normalize_newlines(original)
        previous = mapping.setdefault(key, replacement)
        if previous != replacement:
            raise ValueError("one source string maps to multiple translations")
        if INVALID_XML_CHAR.search(replacement):
            raise ValueError(f"translation contains an invalid XML character: {replacement!r}")

    shutil.copytree(args.english_locale, args.output_locale)
    files = sorted(args.output_locale.rglob("*.stringtable"))
    replaced = 0
    changed = 0
    missing: list[dict[str, str]] = []

    for path in files:
        raw = path.read_bytes()
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")

        def replace(match: re.Match[str]) -> str:
            nonlocal replaced, changed
            encoded = match.group(2)
            original = html.unescape(encoded)
            if not original.strip():
                return match.group(0)
            key = normalize_newlines(original)
            replacement = mapping.get(key)
            if replacement is None:
                missing.append(
                    {
                        "file": str(path.relative_to(args.output_locale)),
                        "field": match.group(1),
                        "text": original[:200],
                    }
                )
                return match.group(0)
            replaced += 1
            changed += replacement != original
            return f"<{match.group(1)}>{xml_escape(replacement)}</{match.group(1)}>"

        output = TEXT_NODE.sub(replace, text)
        payload = output.encode("utf-8")
        if has_bom:
            payload = b"\xef\xbb\xbf" + payload
        path.write_bytes(payload)

    if missing:
        report = args.output_locale.parent / "missing_stringtable_mappings.json"
        report.write_text(json.dumps(missing, ensure_ascii=False, indent=2), encoding="utf-8")
        raise RuntimeError(f"{len(missing)} non-empty fields had no mapping; see {report}")

    # Parse every generated XML document and count its non-empty text fields.
    verified = 0
    chinese_fields = 0
    for path in files:
        root = ET.parse(path).getroot()
        for entry in root.findall(".//Entry"):
            for name in ("DefaultText", "FemaleText"):
                node = entry.find(name)
                value = "" if node is None else "".join(node.itertext())
                if value.strip():
                    verified += 1
                    chinese_fields += bool(re.search(r"[\u3400-\u9fff]", value))

    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(args.output_locale)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())

    summary = {
        "files": len(files),
        "mapping_records": len(mapping),
        "replaced_fields": replaced,
        "changed_fields": changed,
        "verified_nonempty_fields": verified,
        "fields_containing_cjk": chinese_fields,
        "tree_sha256": digest.hexdigest().upper(),
        "output": str(args.output_locale),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if verified != replaced:
        raise RuntimeError(f"verification count mismatch: {verified} != {replaced}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
