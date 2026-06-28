"""`wiki query | search | read | sources-for` — read-only commands.

These acquire a SHARED lock and never mutate the wiki. They implement the
progressive search ladder's lexical tiers (index + filename/heading/text
search). QMD hybrid search is an optional adapter layered on top when present;
the MVP ships the lexical fallback.

`query`        higher-level question answering surface (lexical retrieval +
               pointers to canonical pages; the agent composes the answer).
`search`       raw lexical search over canonical pages.
`read`         print a page's content (and its claims/sources).
`sources-for`  list the sources backing a page (via its claims + frontmatter).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..core.claims import extract_claims
from ..core.context import Context
from ..core.pages import parse_page
from ..core.session import reader_session
from ..core.validators import collect_all_pages
from ..errors import UsageError
from ..output import emit, info


def register(subparsers):
    q = subparsers.add_parser("query", help="Lexically retrieve pages relevant to a question.")
    q.add_argument("question")
    q.add_argument("--limit", type=int, default=8)
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=run_query)

    s = subparsers.add_parser("search", help="Lexical search over canonical pages.")
    s.add_argument("term")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=run_search)

    r = subparsers.add_parser("read", help="Read a page including its claims and sources.")
    r.add_argument("path")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=run_read)

    sf = subparsers.add_parser("sources-for", help="List sources backing a page.")
    sf.add_argument("path")
    sf.add_argument("--json", action="store_true")
    sf.set_defaults(func=run_sources_for)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2]


def _score(page, terms: list[str]) -> int:
    hay_title = (page.frontmatter.get("title", "") + " " + (page.id or "")).lower()
    hay_body = page.body.lower()
    score = 0
    for t in terms:
        score += 5 * hay_title.count(t)
        score += hay_body.count(t)
    return score


def run_query(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    with reader_session(ctx, "wiki query"):
        pages = collect_all_pages(repo)
        terms = _tokens(args.question)
        scored = [(p, _score(p, terms)) for p in pages]
        scored = [(p, sc) for p, sc in scored if sc > 0]
        scored.sort(key=lambda t: t[1], reverse=True)
        hits = scored[: args.limit]
        results = [{
            "id": p.id, "title": p.frontmatter.get("title"),
            "path": repo.rel(p.path), "type": p.type, "score": sc,
        } for p, sc in hits]
    if args.json:
        emit({"question": args.question, "results": results}, as_json=True)
    else:
        if not results:
            info("No matching pages. (Consult raw sources or broaden the query.)")
        for r in results:
            info(f"  [{r['score']:>4}] {r['path']}  {r['title']} `{r['id']}`")
    return 0


def run_search(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    with reader_session(ctx, "wiki search"):
        pages = collect_all_pages(repo)
        term = args.term.lower()
        results = []
        for p in pages:
            count = p.body.lower().count(term) + (p.frontmatter.get("title", "").lower().count(term))
            if count:
                results.append({"path": repo.rel(p.path), "id": p.id, "hits": count})
        results.sort(key=lambda r: r["hits"], reverse=True)
        results = results[: args.limit]
    if args.json:
        emit({"term": args.term, "results": results}, as_json=True)
    else:
        for r in results:
            info(f"  {r['hits']:>4}  {r['path']} `{r['id']}`")
    return 0


def run_read(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    target = (repo.root / args.path).resolve()
    if not target.exists():
        raise UsageError(f"page not found: {args.path}")
    with reader_session(ctx, "wiki read"):
        page = parse_page(target)
        claims = extract_claims(page.body)
    if args.json:
        emit({
            "path": repo.rel(target),
            "frontmatter": page.frontmatter,
            "claims": [{"id": c.id, "status": c.status, "sources": c.sources, "text": c.text}
                       for c in claims],
            "body": page.body,
        }, as_json=True)
    else:
        info(page.raw_text)
        if claims:
            info("\n-- claims --")
            for c in claims:
                info(f"  {c.id} [{c.status}] sources={c.sources}")
    return 0


def run_sources_for(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    target = (repo.root / args.path).resolve()
    if not target.exists():
        raise UsageError(f"page not found: {args.path}")
    with reader_session(ctx, "wiki sources-for"):
        page = parse_page(target)
        claims = extract_claims(page.body)
        sources = set(page.sources)
        for c in claims:
            for s in c.sources:
                sources.add(s)
    src_list = sorted(sources)
    if args.json:
        emit({"path": repo.rel(target), "sources": src_list}, as_json=True)
    else:
        for s in src_list:
            info(f"  {s}")
    return 0
