"""Derived state generation (plan sections: index budget, claim index, metrics).

All of this is rebuildable with `wiki rebuild`. Losing it slows operations but
never loses provenance, because it is regenerated from canonical sources,
pages, claims and the event log.

  * manifest.json     source hashes + processing state, from descriptors+events
  * backlinks.json    page -> inbound links and citing pages
  * claim-index.json  source<->claim<->page maps (plan section 9)
  * index.md          size-budgeted routing index; overflow -> category indexes
"""

from __future__ import annotations

import json
from pathlib import Path

from .claims import extract_claims
from .events import EventLog
from .pages import Page
from .paths import Repo
from .sources import parse_source
from .validators import collect_all_pages


# -- claim index ------------------------------------------------------------

def build_claim_index(repo: Repo, pages: list[Page] | None = None) -> dict:
    pages = pages if pages is not None else collect_all_pages(repo)
    source_to_claims: dict[str, list[str]] = {}
    claim_to_sources: dict[str, list[str]] = {}
    claim_to_page: dict[str, str] = {}
    page_to_claims: dict[str, list[str]] = {}
    claim_status: dict[str, str] = {}

    for page in pages:
        rel = repo.rel(page.path)
        claims = extract_claims(page.body)
        page_to_claims[rel] = []
        for c in claims:
            page_to_claims[rel].append(c.id)
            claim_to_page[c.id] = rel
            claim_to_sources[c.id] = list(c.sources)
            claim_status[c.id] = c.status
            for src in c.sources:
                base = src.split("#", 1)[0]
                source_to_claims.setdefault(base, [])
                if c.id not in source_to_claims[base]:
                    source_to_claims[base].append(c.id)

    return {
        "source_to_claims": source_to_claims,
        "claim_to_sources": claim_to_sources,
        "claim_to_page": claim_to_page,
        "page_to_claims": page_to_claims,
        "claim_status": claim_status,
    }


# -- backlinks --------------------------------------------------------------

def build_backlinks(repo: Repo, pages: list[Page] | None = None) -> dict:
    pages = pages if pages is not None else collect_all_pages(repo)
    by_id = {p.id: repo.rel(p.path) for p in pages if p.id}
    inbound: dict[str, list[str]] = {p.id: [] for p in pages if p.id}
    for page in pages:
        if not page.id:
            continue
        for linked in page.page_links:
            if linked in inbound and page.id not in inbound[linked]:
                inbound[linked].append(page.id)
    return {"page_ids": by_id, "inbound": inbound}


# -- manifest ---------------------------------------------------------------

def build_manifest(repo: Repo) -> dict:
    sources = {}
    if repo.sources.is_dir():
        for sp in sorted(repo.sources.glob("*.md")):
            try:
                src = parse_source(sp)
            except Exception:
                continue
            sid = src.source_id
            if not sid:
                continue
            sources[sid] = {
                "status": src.status,
                "sha256": src.sha256,
                "storage": src.storage,
                "evidence_class": src.evidence_class,
                "classification_status": src.classification_status,
                "descriptor": repo.rel(sp),
            }
    log = EventLog(repo.events)
    return {
        "generated_from": "sources + events",
        "max_seq": log.max_seq(),
        "sources": sources,
    }


# -- root index (size-budgeted) ---------------------------------------------

def _page_links_by_type(repo: Repo, pages: list[Page]) -> dict[str, list[tuple[str, str, str]]]:
    by_type: dict[str, list[tuple[str, str, str]]] = {}
    for page in pages:
        if not page.id or not page.type:
            continue
        rel = repo.rel(page.path)
        title = page.frontmatter.get("title", page.id)
        by_type.setdefault(page.type, []).append((page.id, title, rel))
    for k in by_type:
        by_type[k].sort(key=lambda t: t[0])
    return by_type


def generate_indexes(repo: Repo, schema: dict, pages: list[Page] | None = None) -> dict:
    """Generate root index.md and, when needed, per-category indexes.

    Returns a dict of {repo_relative_path: content} for the caller to stage and
    commit through an operation (so generation participates in the journal)."""
    pages = pages if pages is not None else collect_all_pages(repo)
    limits = schema.get("limits", {})
    max_lines = limits.get("root_index_max_lines", 200)
    max_bytes = limits.get("root_index_max_bytes", 24576)
    max_links = limits.get("root_index_max_links", 100)

    by_type = _page_links_by_type(repo, pages)
    total_links = sum(len(v) for v in by_type.values())

    # Decide whether the flat index fits the budget. We build a candidate and
    # measure it; if it exceeds any budget we switch to a routing index that
    # links to generated category indexes.
    type_dir = schema.get("pageTypeDir", {})
    outputs: dict[str, str] = {}

    open_reviews_note = ""

    def flat_index() -> str:
        lines = ["# Wiki Index", "", "Generated routing index. Do not hand-edit.", ""]
        for ptype in sorted(by_type):
            lines.append(f"## {ptype}")
            lines.append("")
            for pid, title, rel in by_type[ptype]:
                lines.append(f"- [{title}](../{rel}) `{pid}`")
            lines.append("")
        return "\n".join(lines).rstrip("\n") + "\n"

    candidate = flat_index()
    fits = (
        candidate.count("\n") + 1 <= max_lines
        and len(candidate.encode("utf-8")) <= max_bytes
        and total_links <= max_links
    )

    if fits:
        outputs[repo.rel(repo.index_md)] = candidate
        return outputs

    # Overflow: routing index + per-category indexes.
    routing_lines = ["# Wiki Index", "", "Generated routing index. Do not hand-edit.", ""]
    routing_lines.append("This wiki exceeds the root index budget; categories are split out.")
    routing_lines.append("")
    for ptype in sorted(by_type):
        dir_name = type_dir.get(ptype, ptype)
        cat_rel = f"wiki/pages/{dir_name}/_index.md"
        count = len(by_type[ptype])
        routing_lines.append(f"- **{ptype}** ({count}) -> [{dir_name}/_index.md](pages/{dir_name}/_index.md)")
        # build category index
        cat_lines = [f"# {ptype} index", "", "Generated. Do not hand-edit.", ""]
        for pid, title, rel in by_type[ptype]:
            # category index sits inside the category dir; link relative to it
            cat_lines.append(f"- [{title}](../../../{rel}) `{pid}`")
        outputs[cat_rel] = "\n".join(cat_lines).rstrip("\n") + "\n"
    routing_lines.append("")
    outputs[repo.rel(repo.index_md)] = "\n".join(routing_lines).rstrip("\n") + "\n"
    return outputs


# -- persistence of derived caches -----------------------------------------

def write_caches(repo: Repo, pages: list[Page] | None = None):
    repo.cache.mkdir(parents=True, exist_ok=True)
    pages = pages if pages is not None else collect_all_pages(repo)
    repo.claim_index.write_text(json.dumps(build_claim_index(repo, pages), indent=2), encoding="utf-8")
    repo.backlinks.write_text(json.dumps(build_backlinks(repo, pages), indent=2), encoding="utf-8")
    repo.manifest.write_text(json.dumps(build_manifest(repo), indent=2), encoding="utf-8")
