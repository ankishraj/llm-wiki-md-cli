"""Markdown page parsing: frontmatter, headings, citations (plan sections 9, 14).

Pages are Markdown with a YAML frontmatter block delimited by `---` lines.
We use a small dependency-free YAML subset parser for frontmatter so the
zipapp need not vendor PyYAML, but we accept the common scalar/list/mapping
shapes that page frontmatter uses.

Citations in prose use the form [[source-<slug>]] or [[source-<slug>#frag]].
Claim blocks (see claims.py) carry their own structured source lists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .hashing import hash_text

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)
CITATION_RE = re.compile(r"\[\[(source-[a-z0-9][a-z0-9-]*(?:#[A-Za-z0-9._:-]+)?)\]\]")
WIKILINK_RE = re.compile(r"\[\[((?:topic|entity|decision|synthesis|note)-[a-z0-9][a-z0-9-]*)\]\]")


@dataclass
class Page:
    path: Path
    frontmatter: dict
    body: str
    raw_text: str
    headings: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    page_links: list[str] = field(default_factory=list)

    @property
    def content_hash(self) -> str:
        return hash_text(self.raw_text)

    @property
    def id(self) -> str | None:
        return self.frontmatter.get("id")

    @property
    def type(self) -> str | None:
        return self.frontmatter.get("type")

    @property
    def status(self) -> str | None:
        return self.frontmatter.get("status")

    @property
    def sources(self) -> list[str]:
        s = self.frontmatter.get("sources")
        return list(s) if isinstance(s, list) else []


def parse_page(path: Path) -> Page:
    text = Path(path).read_text(encoding="utf-8")
    return parse_page_text(path, text)


def parse_page_text(path: Path, text: str) -> Page:
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    m = FRONTMATTER_RE.match(normalised)
    if m:
        fm_text, body = m.group(1), m.group(2)
        frontmatter = parse_frontmatter(fm_text)
    else:
        frontmatter, body = {}, normalised
    headings = [h.group(0).strip() for h in HEADING_RE.finditer(body)]
    # source_ref locators are dedup'd preserving order
    citations = _unique([m2.group(1) for m2 in CITATION_RE.finditer(body)])
    page_links = _unique([m2.group(1) for m2 in WIKILINK_RE.finditer(body)])
    return Page(
        path=Path(path),
        frontmatter=frontmatter,
        body=body,
        raw_text=normalised,
        headings=headings,
        citations=citations,
        page_links=page_links,
    )


def _unique(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


# -- minimal YAML frontmatter parser ----------------------------------------
# Supports: `key: scalar`, `key:` followed by `  - item` list lines, quoted
# strings, ints, booleans, null, and inline `[a, b]` lists. This is enough for
# page/source frontmatter and avoids vendoring PyYAML.

def parse_frontmatter(text: str) -> dict:
    result: dict = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            # Possibly a block list following.
            items = []
            j = i + 1
            while j < len(lines) and re.match(r"^\s*-\s+", lines[j]):
                item = re.sub(r"^\s*-\s+", "", lines[j]).strip()
                items.append(_scalar(item))
                j += 1
            if items:
                result[key] = items
                i = j
                continue
            result[key] = None
            i += 1
            continue
        result[key] = _scalar(rest)
        i += 1
    return result


def _scalar(value: str):
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part) for part in _split_inline_list(inner)]
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    return v


def _split_inline_list(inner: str) -> list[str]:
    parts = []
    depth = 0
    cur = ""
    for ch in inner:
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts]


def dump_frontmatter(data: dict) -> str:
    """Serialise frontmatter back to the YAML subset, deterministically."""
    lines = []
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {_dump_scalar(item)}")
        else:
            lines.append(f"{key}: {_dump_scalar(value)}")
    return "\n".join(lines)


def _dump_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    if s == "" or re.search(r"[:#\[\]{}]", s) or s != s.strip():
        return f'"{s}"'
    return s


def build_page_text(frontmatter: dict, body: str) -> str:
    fm = dump_frontmatter(frontmatter)
    body = body.lstrip("\n")
    return f"---\n{fm}\n---\n\n{body}".rstrip("\n") + "\n"
