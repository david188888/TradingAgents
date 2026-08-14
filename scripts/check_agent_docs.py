#!/usr/bin/env python3
"""Validate the repository's Agent-facing Markdown entry points and links.

This checker deliberately uses only the Python standard library. It reads local
Markdown files, validates local link paths and Markdown heading fragments, and
never executes or rewrites repository content.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

REQUIRED_FILES = (
    "README.md",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "docs/README.md",
)
MARKDOWN_SUFFIXES = {".md", ".mdx"}
EXCLUDED_DIRS = {
    ".agents",
    ".cache",
    ".claude",
    ".codex",
    ".git",
    ".github-cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".vite",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "env",
    "frontend/node_modules",
    "htmlcov",
    "node_modules",
    "output",
    "reports",
    "site",
    "target",
    "tmp",
    "venv",
    "worklog",
}
EXCLUDED_FILES = {"CHANGELOG.md", "REFACTOR_PLAN.md"}
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
# The second alternative permits the common unquoted id form without making
# the main Markdown parser dependent on an HTML parser.
HTML_ID_RE = re.compile(
    r"<a\b[^>]*\bid\s*=\s*(?:[\"']([^\"']+)[\"']|([^\"'\s>]+))",
    re.IGNORECASE,
)
HTML_NAME_RE = re.compile(
    r"<a\b[^>]*\bname\s*=\s*(?:[\"']([^\"']+)[\"']|([^\"'\s>]+))",
    re.IGNORECASE,
)
INLINE_LINK_RE = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(?:<(?P<bracket>[^>\n]*)>|(?P<plain>[^\s)\n]+))",
)
REFERENCE_DEFINITION_RE = re.compile(
    r"^\s{0,3}\[(?P<label>[^\]\n]+)\]:\s*(?:<(?P<bracket>[^>\n]*)>|(?P<plain>[^\s]+))",
)
REFERENCE_LINK_RE = re.compile(
    r"!?\[(?P<text>[^\]\n]+)\]\[(?P<label>[^\]\n]*)\]"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    return parser.parse_args()


def relative_name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def should_skip(path: Path, root: Path) -> bool:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError:
        return True
    if any(part in EXCLUDED_DIRS for part in relative_parts):
        return True
    return path.name in EXCLUDED_FILES


def markdown_files(root: Path) -> list[Path]:
    command = [
        "git",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        "*.md",
        "*.mdx",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise RuntimeError(f"unable to enumerate Markdown files with Git: {exc}") from exc
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Git Markdown enumeration failed (exit {result.returncode}){suffix}")

    files: list[Path] = []
    for raw_path in result.stdout.split(b"\x00"):
        if not raw_path:
            continue
        relative = Path(os.fsdecode(raw_path))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Git returned an unsafe Markdown path: {relative}")
        path = root / relative
        if (
            path.suffix.lower() in MARKDOWN_SUFFIXES
            and not should_skip(path, root)
            and not path.is_symlink()
            and path.is_file()
        ):
            files.append(path)
    return sorted(files, key=lambda path: relative_name(path, root))


def strip_fenced_code(lines: list[str]) -> list[tuple[int, str]]:
    """Return non-fenced lines with their original 1-based line numbers."""
    visible: list[tuple[int, str]] = []
    fence_char: str | None = None
    fence_length = 0
    for line_number, line in enumerate(lines, start=1):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence_char is None:
                fence_char, fence_length = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char, fence_length = None, 0
            continue
        if fence_char is None:
            visible.append((line_number, line))
    return visible


def clean_heading_text(text: str) -> str:
    text = re.sub(r"\s+#+\s*$", "", text)
    text = re.sub(r"!?(\[[^\]]*\])\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def github_slug(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", clean_heading_text(text)).lower()
    normalized = re.sub(r"[^\w\s-]", "", normalized, flags=re.UNICODE)
    return re.sub(r"[\s-]+", "-", normalized).strip("-")


def anchors_for(lines: list[str]) -> set[str]:
    anchors: set[str] = set()
    slug_counts: dict[str, int] = {}
    for _, line in strip_fenced_code(lines):
        heading = HEADING_RE.match(line)
        if heading:
            explicit = re.search(r"\s*\{#([^}\s]+)\}\s*$", heading.group(2))
            if explicit:
                anchors.add(explicit.group(1))
            slug = github_slug(heading.group(2))
            if slug:
                count = slug_counts.get(slug, 0)
                candidate = slug if count == 0 else f"{slug}-{count}"
                slug_counts[slug] = count + 1
                anchors.add(candidate)
        for match in HTML_ID_RE.finditer(line):
            anchors.add(match.group(1) or match.group(2))
        for match in HTML_NAME_RE.finditer(line):
            anchors.add(match.group(1) or match.group(2))
    return anchors


def normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip()).casefold()


def extracted_links(lines: list[str]) -> list[tuple[int, str]]:
    links: list[tuple[int, str]] = []
    for line_number, line in strip_fenced_code(lines):
        definition = REFERENCE_DEFINITION_RE.match(line)
        if definition:
            target = definition.group("bracket") or definition.group("plain")
            if target:
                links.append((line_number, html.unescape(target)))
        for match in INLINE_LINK_RE.finditer(line):
            target = match.group("bracket") or match.group("plain")
            if target:
                links.append((line_number, html.unescape(target)))
    return links


def reference_definitions(lines: list[str]) -> dict[str, tuple[int, str]]:
    definitions: dict[str, tuple[int, str]] = {}
    for line_number, line in strip_fenced_code(lines):
        match = REFERENCE_DEFINITION_RE.match(line)
        if not match:
            continue
        target = match.group("bracket") or match.group("plain")
        if target:
            definitions.setdefault(
                normalize_label(match.group("label")),
                (line_number, html.unescape(target)),
            )
    return definitions


def unresolved_references(lines: list[str], definitions: dict[str, tuple[int, str]]) -> list[tuple[int, str]]:
    unresolved: list[tuple[int, str]] = []
    for line_number, line in strip_fenced_code(lines):
        for match in REFERENCE_LINK_RE.finditer(line):
            label = match.group("label") or match.group("text")
            if normalize_label(label) not in definitions:
                unresolved.append((line_number, f"[{label}]"))
    return unresolved


def local_target(target: str) -> tuple[str, str] | None:
    target = target.strip()
    if not target or target.startswith("#"):
        return None
    parsed = urlsplit(target)
    if parsed.scheme or target.startswith("//"):
        return None
    path_part = unquote(parsed.path)
    fragment = unquote(parsed.fragment)
    return path_part, fragment


def resolve_target(source: Path, path_part: str, root: Path) -> Path | None:
    target = root / path_part.lstrip("/") if path_part.startswith("/") else source.parent / path_part
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    if should_skip(resolved, root):
        return None
    return resolved


def check_file(path: Path, root: Path) -> list[str]:
    name = relative_name(path, root)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [f"{name}: unable to read Markdown file: {exc}"]

    errors: list[str] = []
    definitions = reference_definitions(lines)
    for line_number, reference in unresolved_references(lines, definitions):
        errors.append(f"{name}:{line_number}: unresolved Markdown reference {reference}")

    links = extracted_links(lines)
    for line_number, target in links:
        parsed = local_target(target)
        if parsed is None:
            continue
        path_part, fragment = parsed
        target_path = resolve_target(path, path_part, root)
        if target_path is None:
            errors.append(f"{name}:{line_number}: link target outside checked repository: {target}")
            continue
        if not target_path.exists():
            errors.append(f"{name}:{line_number}: missing local link target: {target}")
            continue
        if fragment and target_path.suffix.lower() in MARKDOWN_SUFFIXES:
            try:
                target_anchors = anchors_for(
                    target_path.read_text(encoding="utf-8", errors="replace").splitlines()
                )
            except OSError as exc:
                errors.append(f"{name}:{line_number}: cannot read link target {target}: {exc}")
                continue
            if fragment not in target_anchors:
                errors.append(f"{name}:{line_number}: missing link fragment: {target}")
    return errors


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        print(f"ERROR: repository root is not a directory: {root}", file=sys.stderr)
        return 2

    errors: list[str] = []
    for required in REQUIRED_FILES:
        path = root / required
        if not path.is_file() or path.is_symlink():
            errors.append(f"missing required documentation file: {required}")

    try:
        files = markdown_files(root)
    except RuntimeError as exc:
        errors.append(str(exc))
        files = []
    for path in files:
        errors.extend(check_file(path, root))

    if errors:
        for error in sorted(errors):
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Agent docs check failed: {len(errors)} error(s)", file=sys.stderr)
        return 1

    print(f"Agent docs check passed: {len(files)} Markdown file(s) scanned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
