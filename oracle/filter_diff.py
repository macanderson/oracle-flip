"""Drops every file section of a unified diff whose path is not on the allowlist or is on the denylist.

Reads the diff on stdin, writes the filtered diff on stdout, and lists the
dropped paths on stderr. Globs use `*` for one path segment, `**` for any
number of segments, and `?` for one character.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SECTION_START = re.compile(r"^diff --git a/(.*?) b/(.*)$", re.MULTILINE)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if ch == "*":
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def matches(path: str, patterns: list[str]) -> bool:
    return any(glob_to_regex(p).match(path) for p in patterns)


def allowed(path: str, allow: list[str], deny: list[str]) -> bool:
    if deny and matches(path, deny):
        return False
    return matches(path, allow) if allow else True


def split_sections(diff: str) -> list[tuple[str | None, str]]:
    """Splits a diff into (path, text) sections. Text before the first header has path None."""
    starts = [m.start() for m in SECTION_START.finditer(diff)]
    if not starts:
        return [(None, diff)] if diff else []
    sections: list[tuple[str | None, str]] = []
    if starts[0] > 0:
        sections.append((None, diff[: starts[0]]))
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(diff)
        text = diff[start:end]
        header = SECTION_START.match(text)
        sections.append((header.group(2) if header else None, text))
    return sections


def filter_diff(diff: str, allow: list[str], deny: list[str]) -> tuple[str, list[str]]:
    kept: list[str] = []
    dropped: list[str] = []
    for path, text in split_sections(diff):
        if path is None:
            continue  # stray preamble is never applied
        if allowed(path, allow, deny):
            kept.append(text)
        else:
            dropped.append(path)
    return "".join(kept), dropped


def read_patterns(path: str | None) -> list[str]:
    if not path:
        return []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-file", help="file of allowlist globs, one per line")
    parser.add_argument("--deny-file", help="file of denylist globs, one per line")
    args = parser.parse_args()
    filtered, dropped = filter_diff(sys.stdin.read(), read_patterns(args.allow_file), read_patterns(args.deny_file))
    sys.stdout.write(filtered)
    for path in dropped:
        sys.stderr.write(f"dropped {path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
