"""Fail on common mojibake sequences in source files."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


DEFAULT_EXTENSIONS = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".py",
    ".tsx",
    ".ts",
    ".txt",
    ".yml",
    ".yaml",
}

SUSPICIOUS_MARKERS = (
    "\u00c3",
    "\u00c2",
    "\u00e2\u20ac",
    "\u00e2\u20ac\u0153",
    "\u00e2\u20ac\u2122",
    "\u00e2\u201e\u00a2",
    "\u00ef\u00b8",
    "\u064b\u06ba",
)

ARABIC_MOJIBAKE_BIGRAMS = (
    "ط§",
    "ظ„",
    "ظٹ",
    "ظ…",
    "ط±",
    "طھ",
    "ط¨",
    "ط¹",
)


def should_scan(path: Path) -> bool:
    if path.suffix.lower() not in DEFAULT_EXTENSIONS:
        return False
    return True


def find_issues(root: Path, arabic_threshold: int) -> list[str]:
    issues: list[str] = []
    ignored_dirs = {"node_modules", "__pycache__", ".git", "dist", "build"}
    paths: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in ignored_dirs]
        current_path = Path(current_root)
        for filename in filenames:
            path = current_path / filename
            if should_scan(path):
                paths.append(path)

    for path in sorted(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            issues.append(f"{path}: invalid UTF-8 ({exc})")
            continue

        for marker in SUSPICIOUS_MARKERS:
            if marker in text:
                issues.append(f"{path}: suspicious mojibake marker {marker!r}")
                break

        bigram_count = sum(text.count(marker) for marker in ARABIC_MOJIBAKE_BIGRAMS)
        if bigram_count >= arabic_threshold:
            issues.append(
                f"{path}: likely Arabic mojibake ({bigram_count} suspicious bigrams)"
            )

    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--arabic-threshold", type=int, default=12)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    issues = find_issues(root, args.arabic_threshold)
    if issues:
        print("Encoding check failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("Encoding check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
