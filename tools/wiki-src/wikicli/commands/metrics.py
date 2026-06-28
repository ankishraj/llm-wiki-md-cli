"""`wiki metrics` — corpus metrics + QMD recommendation (plan section 16).

Computes cheap corpus metrics and emits a RECOMMENDATION about semantic
retrieval. Never auto-installs anything. Thresholds are configurable.
"""

from __future__ import annotations

import json

from ..core.context import Context
from ..core.derived import build_claim_index
from ..core.validators import collect_all_pages
from ..output import emit, info


def register(subparsers):
    p = subparsers.add_parser("metrics", help="Show corpus metrics and retrieval recommendation.")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=run)


def run(args) -> int:
    ctx = Context.load()
    repo = ctx.repo
    pages = collect_all_pages(repo)

    page_count = len(pages)
    text_bytes = sum(len(p.raw_text.encode("utf-8")) for p in pages)
    claim_index = build_claim_index(repo, pages)
    claim_count = len(claim_index["claim_to_page"])

    cfg = ctx.retrieval_cfg
    rec_pages = cfg.get("qmd_recommend_pages", 250)
    rec_bytes = cfg.get("qmd_recommend_bytes", 5 * 1024 * 1024)

    reasons = []
    if page_count > rec_pages:
        reasons.append(f"canonical pages ({page_count}) exceed {rec_pages}")
    if text_bytes > rec_bytes:
        reasons.append(f"text size ({text_bytes} bytes) exceeds {rec_bytes}")

    recommend_qmd = bool(reasons)

    metrics = {
        "page_count": page_count,
        "text_bytes": text_bytes,
        "claim_count": claim_count,
        "recommend_qmd": recommend_qmd,
        "reasons": reasons,
        "thresholds": {"pages": rec_pages, "bytes": rec_bytes},
    }
    repo.cache.mkdir(parents=True, exist_ok=True)
    repo.metrics_file.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    if args.json:
        emit(metrics, as_json=True)
    else:
        info(f"pages: {page_count}")
        info(f"text:  {text_bytes} bytes")
        info(f"claims: {claim_count}")
        if recommend_qmd:
            info("\nSemantic retrieval recommended:")
            for r in reasons:
                info(f"  - {r}")
        else:
            info("\nLexical retrieval is sufficient at this corpus size.")
    return 0
