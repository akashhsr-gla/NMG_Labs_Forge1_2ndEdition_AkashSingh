"""
analyzer.py - deterministic internal-linking + topical-authority analysis from a
Screaming Frog export (internal_html.csv + all_inlinks.csv + all_outlinks.csv +
all_anchor_text.csv + a page text/ folder).

STARTER IMPLEMENTATION. It already builds the internal link graph, detects orphan
pages, deepest pages, broken/redirect/nofollow internal links and basic anchor-text
problems so the pipeline runs end to end. Your job in the build is to COMPLETE the
analysis (see rulebook.md): finish the anchor classes, build the topical clusters,
the entity graph, and feed the linker. The grader uses these same definitions.

Standard library only (csv). The heavy lifting (graph, orphans, anchor classes) is
deterministic Python on purpose - the model is for entity extraction, cluster naming
and writing the contextual link suggestions, NOT for counting rows.
"""
from __future__ import annotations
import csv, os, re, math
from collections import defaultdict, Counter
from urllib.parse import urlparse

csv.field_size_limit(10_000_000)

# --------------------------------------------------------------------------- #
# generic / non-descriptive anchors (lowercased, stripped). Extend per rulebook.
# --------------------------------------------------------------------------- #
GENERIC_ANCHORS = {
    "click here", "read more", "read more...", "learn more", "more", "here",
    "this", "this page", "link", "view more", "see more", "details", "more details",
    "know more", "discover more", "find out more", "continue reading", "go",
    "click", "view", "see details", "more info", "info",
    "read here", "learn here", "visit page", "explore more", "check this out",
    "get started", "see also", "read full article", "click for more","visit","explore","learn","read","see"
}

STOPWORDS = set("""a an the and or but if then else for to of in on at by with from as is are was were be been being this that these those it its we you they he she them our your their i me my mine our ours us not no yes do does did doing have has had having will would can could should may might must shall about into over under again further once here there all any both each few more most other some such only own same so than too very s t can just don now get got also into out up down off above below""".split())


# --------------------------------------------------------------------------- #
# parsing helpers
# --------------------------------------------------------------------------- #
def _int(v, d=0):
    try:
        return int(float(str(v).strip()))
    except Exception:
        return d


def _norm(u: str) -> str:
    """Normalise a URL for matching (drop trailing slash, fragment)."""
    if not u:
        return ""
    u = u.split("#")[0].strip()
    if len(u) > 1 and u.endswith("/"):
        u = u[:-1]
    return u


def is_html(r):  return "text/html" in (r.get("Content Type", "") or "").lower()
def is_200(r):   return _int(r.get("Status Code")) == 200
def indexable(r): return (r.get("Indexability", "") or "").strip().lower() == "indexable"


def load_pages(export_dir: str) -> list[dict]:
    """Load internal_html.csv (falls back to internal_all.csv)."""
    for name in ("internal_html.csv", "internal_all.csv"):
        p = os.path.join(export_dir, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
    raise FileNotFoundError("internal_html.csv / internal_all.csv not found in export dir")


def load_links(export_dir: str, fname="all_inlinks.csv") -> list[dict]:
    p = os.path.join(export_dir, fname)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_page_text(export_dir: str) -> dict:
    """Map normalised URL -> body text from the page text/ folder.

    Filenames are URL-encoded, e.g.
      original_https_nmgtechnologies.com_advanced-seo-case-studies.txt
    We reconstruct the URL by stripping the prefix and decoding.
    """
    out = {}
    folder = None
    for cand in ("page text", "page_text", "pagetext"):
        d = os.path.join(export_dir, cand)
        if os.path.isdir(d):
            folder = d
            break
    if not folder:
        return out
    from urllib.parse import unquote
    for fn in os.listdir(folder):
        if not fn.endswith(".txt"):
            continue
        stem = fn[:-4]
        stem = re.sub(r"^original_", "", stem)
        # original_https_host_path -> https://host/path
        stem = stem.replace("https_", "https://", 1).replace("http_", "http://", 1)
        # remaining underscores in the path segment were '/'
        if "://" in stem:
            scheme, rest = stem.split("://", 1)
            rest = rest.replace("_", "/")
            url = f"{scheme}://{rest}"
        else:
            url = stem.replace("_", "/")
        url = unquote(url)
        try:
            with open(os.path.join(folder, fn), encoding="utf-8", errors="ignore") as f:
                out[_norm(url)] = f.read()
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------- #
# 1. INTERNAL LINK GRAPH  (deterministic - DONE in starter)
# --------------------------------------------------------------------------- #
def build_graph(pages, inlinks):
    """Return graph structures from the crawl.

    Uses only internal Hyperlink rows whose Source AND Destination are crawled
    pages. Returns adjacency (out), reverse adjacency (in), and per-page degree.
    """
    page_set = {_norm(p["Address"]) for p in pages}
    out_adj = defaultdict(set)
    in_adj = defaultdict(set)
    follow_in = defaultdict(int)
    for r in inlinks:
        if r.get("Type") != "Hyperlink":
            continue
        s = _norm(r.get("Source", ""))
        d = _norm(r.get("Destination", ""))
        if not s or not d or s == d:
            continue
        if d not in page_set:
            continue  # only count links pointing at crawled internal pages
        out_adj[s].add(d)
        in_adj[d].add(s)
        if (r.get("Follow", "true") or "true").strip().lower() == "true":
            follow_in[d] += 1
    return {"page_set": page_set, "out": out_adj, "in": in_adj, "follow_in": follow_in}


def graph_stats(pages, inlinks, graph) -> dict:
    """Internal-link graph statistics + structural issues.

    Definitions (match the rulebook):
      orphan_page          : indexable 200 html page with Unique Inlinks == 0
      deepest_pages        : indexable pages at the maximum Crawl Depth (>=3 listed)
      under_linked         : indexable 200 page with Unique Inlinks <= UNDER (default 1)
      over_linked          : page in the top 5% by Unique Inlinks (sitewide nav noise)
      broken_internal_link : all_inlinks rows with Status Code 400-599
      redirect_internal    : all_inlinks rows with Status Code 300-399 (3xx)
      nofollow_internal    : all_inlinks Hyperlink rows with Follow == false
    """
    idx200 = [p for p in pages if is_html(p) and is_200(p) and indexable(p)]
    by_url = {_norm(p["Address"]): p for p in pages}

    # orphans (use SF's own Unique Inlinks column - authoritative)
    orphans = sorted(_norm(p["Address"]) for p in idx200 if _int(p.get("Unique Inlinks")) == 0)

    # deepest
    depth = {_norm(p["Address"]): _int(p.get("Crawl Depth")) for p in idx200}
    maxd = max(depth.values()) if depth else 0
    deepest = sorted([u for u, d in depth.items() if d == maxd])

    # under/over linked by Unique Inlinks
    inl = {_norm(p["Address"]): _int(p.get("Unique Inlinks")) for p in idx200}
    UNDER = 1
    under_linked = sorted([u for u, n in inl.items() if n <= UNDER])
    vals = sorted(inl.values())
    over_thresh = vals[int(len(vals) * 0.95)] if vals else 0
    over_linked = sorted([u for u, n in inl.items() if n >= max(over_thresh, 1) and n == max(vals or [0])][:0]) \
        or sorted([u for u, n in inl.items() if over_thresh and n >= over_thresh])

    # broken / redirect / nofollow internal links (from all_inlinks)
    broken, redir, nofollow = [], [], []
    for r in inlinks:
        sc = _int(r.get("Status Code"))
        typ = r.get("Type", "")
        dst = _norm(r.get("Destination", ""))
        src = _norm(r.get("Source", ""))
        if typ == "Hyperlink" and 400 <= sc <= 599:
            broken.append({"source": src, "destination": dst, "status": sc,
                           "anchor": (r.get("Anchor", "") or "").strip()})
        if typ == "Hyperlink" and 300 <= sc <= 399:
            redir.append({"source": src, "destination": dst, "status": sc,
                          "anchor": (r.get("Anchor", "") or "").strip()})
        if typ == "Hyperlink" and (r.get("Follow", "true") or "").strip().lower() == "false":
            nofollow.append({"source": src, "destination": dst,
                             "anchor": (r.get("Anchor", "") or "").strip()})

    return {
        "pages_total": len(pages),
        "pages_indexable": len(idx200),
        "internal_links": sum(len(v) for v in graph["out"].values()),
        "max_crawl_depth": maxd,
        "orphan_pages": orphans,
        "deepest_pages": deepest,
        "under_linked_pages": under_linked,
        "over_linked_pages": over_linked,
        "broken_internal_links": broken,
        "redirect_internal_links": redir,
        "nofollow_internal_links": nofollow,
        "avg_inlinks": round(sum(inl.values()) / len(inl), 1) if inl else 0,
    }


# --------------------------------------------------------------------------- #
# 2. ANCHOR TEXT ANALYSIS  (starter: generic + empty done; TODO: exact-match)
# --------------------------------------------------------------------------- #
def anchor_analysis(inlinks) -> dict:
    """Classify internal Hyperlink anchors.

    generic_anchors      : anchor (lowercased) in GENERIC_ANCHORS
    empty_or_image_only  : Hyperlink row with empty Anchor (image link / bare link)
    over_optimized       : TODO - the SAME exact-match keyword anchor used to point at
                           one destination from many sources (keyword stuffing signal)
    """
    hyper = [r for r in inlinks if r.get("Type") == "Hyperlink"]
    generic, empty = [], []
    dest_anchor = defaultdict(Counter)  # destination -> Counter(anchor)
    for r in hyper:
        a = (r.get("Anchor", "") or "").strip()
        al = a.lower()
        src = _norm(r.get("Source", ""))
        dst = _norm(r.get("Destination", ""))
        if not a:
            empty.append({"source": src, "destination": dst})
            continue
        if al in GENERIC_ANCHORS:
            generic.append({"source": src, "destination": dst, "anchor": a})
        dest_anchor[dst][al] += 1

    # TODO (build): over-optimized exact-match. Starter flags destinations where a
    # single non-generic anchor accounts for a large share AND a high count.
    over = []
    for dst, ctr in dest_anchor.items():
        total = sum(ctr.values())
        if total < 10:
            continue
        anchor, cnt = ctr.most_common(1)[0]
        if anchor and anchor not in GENERIC_ANCHORS and cnt / total >= 0.6 and cnt >= 10:
            over.append({"destination": dst, "anchor": anchor, "count": cnt, "share": round(cnt / total, 2)})

    return {
        "generic_anchors": generic,
        "empty_or_image_only": empty,
        "over_optimized_anchors": sorted(over, key=lambda x: -x["count"]),
        "total_internal_anchors": len(hyper),
    }


# --------------------------------------------------------------------------- #
# 3. TOPICAL CLUSTERS  (starter: path-prefix + keyword TF; TODO: refine + name)
# --------------------------------------------------------------------------- #
def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9\-]{2,}", (text or "").lower())
            if w not in STOPWORDS]


def page_keywords(page, body: str, top=12) -> list[str]:
    """Cheap TF keywords from Title + H1 + H2 + body (deterministic)."""
    import inspect
    import re
    from collections import Counter

    # Initialize cache on the function object
    if not hasattr(page_keywords, "cache"):
        page_keywords.cache = None

    # Lazy-build sitewide frequency filter
    if page_keywords.cache is None:
        caller = inspect.currentframe().f_back

        all_pages = caller.f_locals.get("pages", [])
        all_texts = caller.f_locals.get("page_text", {})

        idx200 = [
            p for p in all_pages
            if is_html(p) and is_200(p) and indexable(p)
        ]

        total_pages = len(idx200)

        if total_pages > 0:
            doc_freq = Counter()

            for p in idx200:
                u = _norm(p["Address"])

                blob = " ".join([
                    p.get("Title 1", "") or "",
                    p.get("H1-1", "") or "",
                    p.get("H2-1", "") or "",
                    p.get("H2-2", "") or "",
                    all_texts.get(u, "")[:6000],
                ])

                tokens = set(
                    re.findall(
                        r"[a-z][a-z0-9\-]{3,}",
                        blob.lower()
                    )
                )

                doc_freq.update(tokens)

            page_keywords.cache = {
                token
                for token, count in doc_freq.items()
                if count / total_pages > 0.30
            }
        else:
            page_keywords.cache = set()

    c = Counter()

    weighted_sources = [
        (page.get("Title 1", "") or "", 5),
        (page.get("H1-1", "") or "", 4),
        (page.get("H2-1", "") or "", 3),
        (page.get("H2-2", "") or "", 3),
        ((body or "")[:6000], 1),
    ]

    for text, weight in weighted_sources:
        tokens = re.findall(
            r"[a-z][a-z0-9\-]{3,}",
            (text or "").lower()
        )

        for token in tokens:
            if token not in page_keywords.cache:
                c[token] += weight

    filtered_c = Counter({
        token: count
        for token, count in c.items()
        if token not in page_keywords.cache
    })

    return [word for word, _ in filtered_c.most_common(top)]


def cluster_pages(pages, page_text, n_keywords=12) -> dict:
    """Group indexable pages into topical clusters using a hybrid approach:
    URL-path grouping + keyword-based splitting for large clusters.
    """

    idx200 = [
        p for p in pages
        if is_html(p) and is_200(p) and indexable(p)
    ]

    # 1. Initial URL-path clustering
    url_clusters = defaultdict(list)
    kw_map = {}

    for p in idx200:
        u = _norm(p["Address"])

        path = urlparse(u).path.strip("/")
        seg = path.split("/")[0] if path else "(home)"

        url_clusters[seg].append(u)

        kw_map[u] = page_keywords(
            p,
            page_text.get(u, ""),
            n_keywords
        )

    # 2. Hybrid splitting for large clusters
    final_clusters = []

    for seg, members in url_clusters.items():

        if len(members) < 25:
            final_clusters.append((seg, members))
            continue

        all_kws = []

        for m in members:
            all_kws.extend(kw_map.get(m, []))

        dominant_kws = [
            w
            for w, c in Counter(all_kws).most_common(8)
        ]

        unassigned = set(members)
        sub_clusters = []

        for kw in dominant_kws:

            matches = [
                m
                for m in unassigned
                if kw in kw_map.get(m, [])
            ]

            if len(matches) >= 3:
                sub_clusters.append(
                    (f"{seg}_{kw}", matches)
                )

                for m in matches:
                    unassigned.remove(m)

        if unassigned:
            sub_clusters.append(
                (
                    f"{seg}_general",
                    list(unassigned)
                )
            )

        final_clusters.extend(sub_clusters)

    # 3. Authority detection + output formatting
    out = []

    inl = {
        _norm(p["Address"]): _int(p.get("Unique Inlinks"))
        for p in idx200
    }

    for key, members in final_clusters:

        members = sorted(members)

        hub = max(
            members,
            key=lambda u: inl.get(u, 0)
        ) if members else None

        hub_inlinks = inl.get(hub, 0)

        member_inl = sorted(
            (inl.get(m, 0) for m in members),
            reverse=True
        )

        clear_hub = (
            len(member_inl) >= 2
            and hub_inlinks >= 2 * (member_inl[1] or 1)
        )

        ck = Counter()

        for m in members:
            ck.update(kw_map.get(m, []))

        top_kws = [
            w
            for w, _ in ck.most_common(10)
        ]

        if top_kws:
            name = top_kws[0].replace("-", " ").title()
        else:
            name = key.replace("_", " ").title()

        out.append({
            "key": key,
            "name": name,
            "size": len(members),
            "pages": members,
            "hub_page": hub,
            "hub_inlinks": hub_inlinks,
            "authority": "hub" if clear_hub else "scattered",
            "keywords": top_kws,
        })

    out.sort(key=lambda x: -x["size"])

    return {
        "clusters": out,
        "page_keywords": kw_map,
    }

# --------------------------------------------------------------------------- #
# 4. ENTITY GRAPH  (starter: TF-overlap relatedness; TODO: model entities)
# --------------------------------------------------------------------------- #
def relatedness(page_keywords: dict, top_per_page=5) -> dict:
    """Page-to-page topical relatedness via keyword (Jaccard) overlap.

    STARTER: uses the deterministic TF keywords as a proxy for entities. The
    entity-agent should replace `page_keywords` with model-extracted entities for
    a sharper graph, then this same overlap math builds the edges.
    """
    urls = list(page_keywords.keys())
    sets = {u: set(page_keywords[u]) for u in urls}
    edges = {}
    for u in urls:
        scored = []
        su = sets[u]
        if not su:
            edges[u] = []
            continue
        for v in urls:
            if v == u:
                continue
            sv = sets[v]
            if not sv:
                continue
            inter = len(su & sv)
            if inter == 0:
                continue
            jac = inter / len(su | sv)
            scored.append((v, round(jac, 3), sorted(su & sv)[:6]))
        scored.sort(key=lambda x: -x[1])
        edges[u] = [{"to": v, "score": s, "shared": sh} for v, s, sh in scored[:top_per_page]]
    return edges


# --------------------------------------------------------------------------- #
# 5. CONTEXTUAL LINK RECOMMENDATIONS  (starter: candidates; model writes anchors)
# --------------------------------------------------------------------------- #
def link_candidates(graph, relate: dict, pages, max_per_page=5) -> list:
    """
    For each important page, find topically-related pages it does NOT already
    link to.

    Ranking:
        70% topical relatedness
        30% page quality

    Page quality is determined using:
        - Word Count
        - Unique Inlinks
        - Link Score
        - Crawl Depth

    Archive/navigation pages are penalized but not excluded.
    """

    idx200 = [
        p for p in pages
        if is_html(p) and is_200(p) and indexable(p)
    ]

    # -----------------------------
    # Normalization statistics
    # -----------------------------
    max_inlinks = max(
     (_int(p.get("Unique Inlinks"), 0) for p in idx200),
     default=1
    )

    max_link_score = max(
     (_int(p.get("Link Score"), 0) for p in idx200),
     default=1
    )

    max_depth = max(
     (_int(p.get("Crawl Depth"), 0) for p in idx200),
     default=1
    )
    max_inlinks = max(max_inlinks, 1)
    max_link_score = max(max_link_score, 1)
    max_depth = max(max_depth, 1)
    def url_type_multiplier(url):
      multiplier = 1.0
      url = url.lower()

      if "/author/" in url:
        multiplier *= 0.40

      if "/tag/" in url:
        multiplier *= 0.40

      if "/category/" in url:
        multiplier *= 0.50

      if "/page/" in url:
        multiplier *= 0.30

      if "/feed/" in url:
        multiplier *= 0.20

      return multiplier
    # -----------------------------
    # Page quality score
    # -----------------------------
    def page_quality(page):
     word_count = _int(page.get("Word Count"), 0)
     unique_inlinks = _int(page.get("Unique Inlinks"), 0)
     link_score = _int(page.get("Link Score"), 0)
     crawl_depth = _int(page.get("Crawl Depth"), 0)

     word_score = min(word_count / 2000.0, 1.0)

     inlink_score = (
        min(unique_inlinks / max_inlinks, 1.0)
        if max_inlinks > 0 else 0.0
     )

     link_score_norm = (
        min(link_score / max_link_score, 1.0)
        if max_link_score > 0 else 0.0
     )

     depth_score = (
        1.0 - min(crawl_depth / max_depth, 1.0)
        if max_depth > 0 else 0.0
     )

     return (
        0.35 * word_score +
        0.35 * inlink_score +
        0.20 * link_score_norm +
        0.10 * depth_score
     )

    # -----------------------------
    # Precompute quality
    # -----------------------------
    qualities = {}

    for p in idx200:
        qualities[_norm(p["Address"])] = page_quality(p)

    # Important pages = top hubs
    inl = {
        _norm(p["Address"]): _int(p.get("Unique Inlinks"))
        for p in idx200
    }

    important = sorted(
        inl,
        key=lambda u: -inl[u]
    )[:40]

    out = []

    for u in important:

        already = graph["out"].get(u, set())

        scored_candidates = []

        for e in relate.get(u, []):

            v = e["to"]

            if v in already or v == u:
                continue

            relatedness_score = e["score"]
            quality_score = qualities.get(v, 0.0)

            final_score = (
              0.70 * relatedness_score +
              0.30 * quality_score
             ) * url_type_multiplier(v)

            scored_candidates.append({
                "target": v,
                "relatedness": relatedness_score,
                "shared_topics": e["shared"],
                "suggested_anchor": None,
                "_score": final_score,
            })

        scored_candidates.sort(
            key=lambda x: x["_score"],
            reverse=True
        )

        final_candidates = []

        for c in scored_candidates[:max_per_page]:
            final_candidates.append({
                "target": c["target"],
                "relatedness": c["relatedness"],
                "shared_topics": c["shared_topics"],
                "suggested_anchor": c["suggested_anchor"],
            })

        if final_candidates:
            out.append({
                "source": u,
                "candidates": final_candidates,
            })

    return out

# --------------------------------------------------------------------------- #
# orchestration entry used by server.py / run.py
# --------------------------------------------------------------------------- #
def analyze(export_dir: str) -> dict:
    pages = load_pages(export_dir)
    inlinks = load_links(export_dir, "all_inlinks.csv")
    text = load_page_text(export_dir)
    graph = build_graph(pages, inlinks)
    gstats = graph_stats(pages, inlinks, graph)
    anchors = anchor_analysis(inlinks)
    clusters = cluster_pages(pages, text)
    relate = relatedness(clusters["page_keywords"])
    cands = link_candidates(graph, relate, pages)
    return {
        "pages": pages, "graph": graph, "graph_stats": gstats,
        "anchors": anchors, "clusters": clusters, "relatedness": relate,
        "link_candidates": cands, "page_text_count": len(text),
    }


if __name__ == "__main__":
    import sys, json
    d = sys.argv[1] if len(sys.argv) > 1 else "../sample-export"
    res = analyze(d)
    g = res["graph_stats"]
    print(f"pages={g['pages_total']} indexable={g['pages_indexable']} "
          f"links={g['internal_links']} maxdepth={g['max_crawl_depth']}")
    print(f"orphans={len(g['orphan_pages'])} under_linked={len(g['under_linked_pages'])} "
          f"over_linked={len(g['over_linked_pages'])}")
    print(f"broken_internal={len(g['broken_internal_links'])} "
          f"redirect_internal={len(g['redirect_internal_links'])} "
          f"nofollow_internal={len(g['nofollow_internal_links'])}")
    a = res["anchors"]
    print(f"generic_anchors={len(a['generic_anchors'])} empty={len(a['empty_or_image_only'])} "
          f"over_optimized={len(a['over_optimized_anchors'])}")
    print(f"clusters={len(res['clusters']['clusters'])} "
          f"link_candidate_pages={len(res['link_candidates'])} "
          f"page_text={res['page_text_count']}")
