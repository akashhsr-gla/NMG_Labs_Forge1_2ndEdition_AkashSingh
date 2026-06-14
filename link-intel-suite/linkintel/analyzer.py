"""
analyzer.py - deterministic internal-linking + topical-authority analysis from a
Screaming Frog export (internal_html.csv + all_inlinks.csv + all_anchor_text.csv
+ a page text/ folder).

FIXED VERSION - rewrites:
  1. page_keywords   - no inspect() hack; sitewide IDF passed explicitly
  2. cluster_pages   - semantic keyword clustering (not path-prefix), merging
                       tiny clusters, deduplication, and meaningful names
  3. relatedness     - cosine-style TF-IDF overlap instead of raw Jaccard
  4. link_candidates - higher threshold, better scoring, anchor draft support
  5. anchor_analysis - over-optimized detection tightened

Standard library only (csv, math, re, collections).
"""
from __future__ import annotations
import csv, os, re, math
from collections import defaultdict, Counter
from urllib.parse import urlparse, unquote

csv.field_size_limit(10_000_000)

# ---------------------------------------------------------------------------
# Generic / non-descriptive anchors
# ---------------------------------------------------------------------------
GENERIC_ANCHORS = {
    "click here", "read more", "read more...", "learn more", "more", "here",
    "this", "this page", "link", "view more", "see more", "details", "more details",
    "know more", "discover more", "find out more", "continue reading", "go",
    "click", "view", "see details", "more info", "info",
    "read here", "learn here", "visit page", "explore more", "check this out",
    "get started", "see also", "read full article", "click for more", "visit",
    "explore", "learn", "read", "see", "page", "website", "site", "article",
    "post", "blog post", "blog", "home", "homepage",
}

STOPWORDS = set(
    "a an the and or but if then else for to of in on at by with from as is are "
    "was were be been being this that these those it its we you they he she them "
    "our your their i me my mine ours us not no yes do does did doing have has had "
    "having will would can could should may might must shall about into over under "
    "again further once here there all any both each few more most other some such "
    "only own same so than too very s t can just don now get got also into out up "
    "down off above below what which who whom how when where why".split()
)

# Words that appear on almost every page and add no signal
SITEWIDE_NOISE = {
    "years", "provided", "similar", "information", "contact", "advanced",
    "learn", "pricing", "home", "welcome", "services", "solutions", "company",
    "page", "website", "site", "email", "phone", "address", "footer", "header",
    "menu", "navigation", "cookie", "privacy", "terms", "rights", "reserved",
    "copyright", "subscribe", "newsletter", "follow", "social", "share",
    "comment", "reply", "submit", "search", "login", "register", "account",
    "free", "trial", "demo", "quote", "price", "cost", "plan", "package",
    "client", "customer", "user", "team", "work", "project", "result",
    "case", "study", "blog", "post", "article", "read", "click", "view",
    "download", "ebook", "guide", "checklist", "resource", "tool",
    "platform", "product", "feature", "benefit", "advantage", "solution",
    "technology", "digital", "online", "global", "world", "industry",
    "business", "company", "brand", "market", "strategy", "growth",
    "success", "quality", "experience", "expertise", "partner", "support",
}

# Broad topic vocabulary for cluster naming
TOPIC_VOCAB = {
    "mobile": ["mobile", "app", "android", "ios", "flutter", "react-native", "swift"],
    "web": ["web", "website", "frontend", "backend", "html", "css", "javascript", "react", "angular", "vue"],
    "ecommerce": ["ecommerce", "shopify", "magento", "woocommerce", "cart", "checkout", "store"],
    "ai": ["artificial-intelligence", "machine-learning", "deep-learning", "neural", "llm", "gpt", "openai", "chatgpt", "automation", "agentic"],
    "cloud": ["cloud", "aws", "azure", "gcp", "devops", "kubernetes", "docker", "microservices"],
    "erp": ["erp", "crm", "sap", "salesforce", "odoo", "dynamics"],
    "healthcare": ["healthcare", "medical", "health", "clinic", "hospital", "patient", "ehr"],
    "fintech": ["fintech", "finance", "banking", "payment", "wallet", "crypto", "blockchain"],
    "security": ["security", "cybersecurity", "encryption", "authentication", "compliance", "gdpr"],
    "seo": ["seo", "search", "google", "ranking", "keyword", "backlink", "organic"],
    "design": ["design", "ux", "ui", "figma", "prototype", "wireframe", "branding"],
    "outsourcing": ["outsourcing", "offshore", "nearshore", "dedicated", "team", "hire", "staff"],
    "enterprise": ["enterprise", "corporate", "b2b", "saas", "software"],
    "startup": ["startup", "mvp", "product", "launch", "scale"],
    "ar_vr": ["augmented-reality", "virtual-reality", "ar", "vr", "metaverse", "3d"],
    "iot": ["iot", "internet-of-things", "sensor", "embedded", "firmware"],
    "blockchain": ["blockchain", "nft", "defi", "smart-contract", "web3"],
    "analytics": ["analytics", "data", "dashboard", "visualization", "reporting", "business-intelligence"],
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def _int(v, d=0):
    try:
        return int(float(str(v).strip()))
    except Exception:
        return d


def _norm(u: str) -> str:
    if not u:
        return ""
    u = u.split("#")[0].strip()
    if len(u) > 1 and u.endswith("/"):
        u = u[:-1]
    return u


def is_html(r):    return "text/html" in (r.get("Content Type", "") or "").lower()
def is_200(r):     return _int(r.get("Status Code")) == 200
def indexable(r):  return (r.get("Indexability", "") or "").strip().lower() == "indexable"


def load_pages(export_dir: str) -> list[dict]:
    for name in ("internal_html.csv", "internal_all.csv"):
        p = os.path.join(export_dir, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
    raise FileNotFoundError("internal_html.csv / internal_all.csv not found")


def load_links(export_dir: str, fname="all_inlinks.csv") -> list[dict]:
    p = os.path.join(export_dir, fname)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_page_text(export_dir: str) -> dict:
    out = {}
    folder = None
    for cand in ("page text", "page_text", "pagetext"):
        d = os.path.join(export_dir, cand)
        if os.path.isdir(d):
            folder = d
            break
    if not folder:
        return out
    for fn in os.listdir(folder):
        if not fn.endswith(".txt"):
            continue
        stem = fn[:-4]
        stem = re.sub(r"^original_", "", stem)
        stem = stem.replace("https_", "https://", 1).replace("http_", "http://", 1)
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


# ---------------------------------------------------------------------------
# 1. INTERNAL LINK GRAPH
# ---------------------------------------------------------------------------
def build_graph(pages, inlinks):
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
            continue
        out_adj[s].add(d)
        in_adj[d].add(s)
        if (r.get("Follow", "true") or "true").strip().lower() == "true":
            follow_in[d] += 1
    return {"page_set": page_set, "out": out_adj, "in": in_adj, "follow_in": follow_in}


def graph_stats(pages, inlinks, graph) -> dict:
    idx200 = [p for p in pages if is_html(p) and is_200(p) and indexable(p)]

    orphans = sorted(_norm(p["Address"]) for p in idx200
                     if _int(p.get("Unique Inlinks")) == 0)

    depth = {_norm(p["Address"]): _int(p.get("Crawl Depth")) for p in idx200}
    maxd = max(depth.values()) if depth else 0
    deepest = sorted([u for u, d in depth.items() if d == maxd])

    inl = {_norm(p["Address"]): _int(p.get("Unique Inlinks")) for p in idx200}
    UNDER = 1
    under_linked = sorted([u for u, n in inl.items() if n <= UNDER])
    vals = sorted(inl.values())
    over_thresh = vals[int(len(vals) * 0.95)] if vals else 0
    over_linked = sorted([u for u, n in inl.items()
                          if over_thresh and n >= over_thresh])

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


# ---------------------------------------------------------------------------
# 2. ANCHOR TEXT ANALYSIS
# ---------------------------------------------------------------------------
def anchor_analysis(inlinks) -> dict:
    hyper = [r for r in inlinks if r.get("Type") == "Hyperlink"]
    generic, empty = [], []
    dest_anchor = defaultdict(Counter)

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
        if dst:
            dest_anchor[dst][al] += 1

    # Over-optimized: same exact non-generic anchor dominates a destination
    over = []
    for dst, ctr in dest_anchor.items():
        total = sum(ctr.values())
        if total < 5:
            continue
        anchor, cnt = ctr.most_common(1)[0]
        if (anchor and anchor not in GENERIC_ANCHORS
                and cnt / total >= 0.5 and cnt >= 5):
            over.append({
                "destination": dst,
                "anchor": anchor,
                "count": cnt,
                "share": round(cnt / total, 2),
            })

    return {
        "generic_anchors": generic,
        "empty_or_image_only": empty,
        "over_optimized_anchors": sorted(over, key=lambda x: -x["count"]),
        "total_internal_anchors": len(hyper),
    }


# ---------------------------------------------------------------------------
# 3. KEYWORD EXTRACTION  (no inspect hack; IDF passed explicitly)
# ---------------------------------------------------------------------------
def _tokenize(text: str) -> list[str]:
    """Lowercase alpha-dash tokens, length ≥ 3, no stopwords."""
    return [w for w in re.findall(r"[a-z][a-z0-9\-]{2,}", (text or "").lower())
            if w not in STOPWORDS and w not in SITEWIDE_NOISE]


def build_idf(pages: list[dict], page_text: dict) -> dict[str, float]:
    """Compute IDF for all tokens across indexable 200 pages."""
    idx200 = [p for p in pages if is_html(p) and is_200(p) and indexable(p)]
    N = len(idx200)
    if N == 0:
        return {}
    doc_freq: Counter = Counter()
    for p in idx200:
        u = _norm(p["Address"])
        blob = " ".join([
            p.get("Title 1", "") or "",
            p.get("H1-1", "") or "",
            p.get("H2-1", "") or "",
            p.get("H2-2", "") or "",
            (page_text.get(u, "") or "")[:8000],
        ])
        doc_freq.update(set(_tokenize(blob)))
    # IDF = log((N+1)/(df+1)) + 1  (smoothed)
    return {tok: math.log((N + 1) / (df + 1)) + 1
            for tok, df in doc_freq.items()}


def page_keywords(page: dict, body: str, idf: dict, top: int = 15) -> list[str]:
    """TF-IDF keywords for a single page. IDF must be pre-computed."""
    weighted_sources = [
        (page.get("Title 1", "") or "", 6),
        (page.get("H1-1", "") or "", 5),
        (page.get("H2-1", "") or "", 3),
        (page.get("H2-2", "") or "", 3),
        (page.get("H2-3", "") or "", 2),
        ((body or "")[:8000], 1),
    ]
    tf: Counter = Counter()
    for text, weight in weighted_sources:
        for tok in _tokenize(text):
            tf[tok] += weight

    # TF-IDF score
    scored = {tok: count * idf.get(tok, 1.0)
              for tok, count in tf.items()}

    # Near-duplicate deduplication (prefix / suffix)
    final: list[str] = []
    for word, _ in sorted(scored.items(), key=lambda x: -x[1]):
        if word in final:
            continue
        is_dup = any(
            len(word) > 4 and len(ex) > 4 and
            (word.startswith(ex[:4]) or ex.startswith(word[:4]))
            for ex in final
        )
        if not is_dup:
            final.append(word)
        if len(final) == top:
            break
    return final


# ---------------------------------------------------------------------------
# 4. TOPICAL CLUSTERS  (semantic keyword clustering, not path-prefix)
# ---------------------------------------------------------------------------
def _url_slug(url: str) -> str:
    """Extract meaningful tokens from URL slug."""
    path = urlparse(url).path.strip("/")
    slug = path.replace("/", " ").replace("-", " ").replace("_", " ")
    return slug.lower()


def _assign_topic(kws: list[str], url: str) -> str | None:
    """Try to assign a broad topic label from TOPIC_VOCAB."""
    combined = set(kws) | set(_tokenize(_url_slug(url)))
    best_topic = None
    best_score = 0
    for topic, vocab in TOPIC_VOCAB.items():
        score = sum(1 for v in vocab if v in combined or
                    any(k.startswith(v[:5]) for k in combined if len(v) > 4))
        if score > best_score:
            best_score = score
            best_topic = topic
    return best_topic if best_score >= 1 else None


def _topic_display_name(topic_key: str) -> str:
    names = {
        "mobile": "Mobile App Development",
        "web": "Web Development",
        "ecommerce": "eCommerce",
        "ai": "AI & Machine Learning",
        "cloud": "Cloud & DevOps",
        "erp": "ERP / CRM",
        "healthcare": "Healthcare",
        "fintech": "FinTech",
        "security": "Cybersecurity",
        "seo": "SEO",
        "design": "UX/UI Design",
        "outsourcing": "IT Outsourcing",
        "enterprise": "Enterprise Software",
        "startup": "Startup / MVP",
        "ar_vr": "AR / VR",
        "iot": "IoT",
        "blockchain": "Blockchain / Web3",
        "analytics": "Analytics & BI",
    }
    return names.get(topic_key, topic_key.replace("_", " ").title())


def cluster_pages(pages: list[dict], page_text: dict) -> dict:
    """
    Semantic keyword clustering:
      1. Build per-page TF-IDF keywords (with sitewide IDF)
      2. Assign each page to a broad topic via TOPIC_VOCAB
      3. Pages that don't match any topic → fallback path-prefix bucket
      4. Merge any bucket with < MIN_SIZE into 'Other'
      5. Compute hub + authority for each cluster
    """
    MIN_CLUSTER_SIZE = 3  # merge smaller clusters into Other

    idx200 = [p for p in pages if is_html(p) and is_200(p) and indexable(p)]
    idf = build_idf(pages, page_text)

    kw_map: dict[str, list[str]] = {}
    topic_map: dict[str, str] = {}  # url -> topic key

    for p in idx200:
        u = _norm(p["Address"])
        kws = page_keywords(p, page_text.get(u, ""), idf)
        kw_map[u] = kws
        topic = _assign_topic(kws, u)
        if topic:
            topic_map[u] = topic

    # Group by topic
    buckets: dict[str, list[str]] = defaultdict(list)
    for p in idx200:
        u = _norm(p["Address"])
        if u in topic_map:
            buckets[topic_map[u]].append(u)
        else:
            # Fallback: first meaningful path segment
            path = urlparse(u).path.strip("/")
            seg = path.split("/")[0] if path else "_home"
            buckets[f"_path_{seg}"].append(u)

    # Merge tiny clusters into "other"
    other: list[str] = []
    final_buckets: dict[str, list[str]] = {}
    for key, members in buckets.items():
        if len(members) < MIN_CLUSTER_SIZE and key.startswith("_path_"):
            other.extend(members)
        else:
            final_buckets[key] = members
    if other:
        final_buckets["other"] = other

    # Build output
    inl = {_norm(p["Address"]): _int(p.get("Unique Inlinks")) for p in idx200}
    out = []

    for key, members in sorted(final_buckets.items(), key=lambda x: -len(x[1])):
        members = sorted(members)
        hub = max(members, key=lambda u: inl.get(u, 0)) if members else None
        hub_inlinks = inl.get(hub, 0) if hub else 0

        member_inl = sorted((inl.get(m, 0) for m in members), reverse=True)
        clear_hub = (
            len(member_inl) >= 2
            and hub_inlinks >= 2 * (member_inl[1] if member_inl[1] else 1)
        )

        # Cluster keywords = union of member keywords, ranked by frequency
        ck: Counter = Counter()
        for m in members:
            ck.update(kw_map.get(m, []))
        top_kws = [w for w, _ in ck.most_common(12)]

        # Display name
        if key.startswith("_"):
            if top_kws:
                name = top_kws[0].replace("-", " ").title()
            else:
                name = key.lstrip("_").replace("path_", "").replace("_", " ").title()
        else:
            name = _topic_display_name(key)

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
    return {"clusters": out, "page_keywords": kw_map, "idf": idf}


# ---------------------------------------------------------------------------
# 5. ENTITY GRAPH  (cosine-style TF-IDF overlap, much sharper than Jaccard)
# ---------------------------------------------------------------------------
def relatedness(page_keywords: dict, idf: dict | None = None,
                top_per_page: int = 20) -> dict:
    """
    Page-to-page topical relatedness using weighted keyword overlap.

    Score = sum of IDF weights of shared keywords / sqrt(|A|*|B|)
    (cosine similarity on the IDF-weighted keyword vectors)

    Falls back to plain Jaccard if no IDF supplied.
    """
    urls = list(page_keywords.keys())
    # Build IDF-weighted vectors
    if idf:
        vecs = {u: {k: idf.get(k, 1.0) for k in kws}
                for u, kws in page_keywords.items()}
        norms = {u: math.sqrt(sum(w * w for w in v.values())) or 1.0
                 for u, v in vecs.items()}
    else:
        vecs = {u: {k: 1.0 for k in kws} for u, kws in page_keywords.items()}
        norms = {u: math.sqrt(len(v)) or 1.0 for u, v in vecs.items()}

    edges: dict[str, list] = {}
    for u in urls:
        vu = vecs[u]
        if not vu:
            edges[u] = []
            continue
        scored = []
        for v in urls:
            if v == u:
                continue
            vv = vecs[v]
            if not vv:
                continue
            shared_keys = set(vu) & set(vv)
            if not shared_keys:
                continue
            dot = sum(vu[k] * vv[k] for k in shared_keys)
            score = dot / (norms[u] * norms[v])
            if score >= 0.05:   # minimum signal threshold
                scored.append((v, round(score, 4), sorted(shared_keys)[:8]))
        scored.sort(key=lambda x: -x[1])
        edges[u] = [{"to": v, "score": s, "shared": sh}
                    for v, s, sh in scored[:top_per_page]]
    return edges


# ---------------------------------------------------------------------------
# 6. CONTEXTUAL LINK RECOMMENDATIONS
# ---------------------------------------------------------------------------
def _draft_anchor(source_kws: list[str], target_kws: list[str],
                  shared: list[str], target_url: str) -> str:
    """
    Draft a descriptive anchor text from shared / target keywords.
    Priority: shared signal words > target-unique words > URL slug words.
    """
    # Pull most meaningful shared keyword(s)
    candidates = [w for w in shared if w not in STOPWORDS and w not in SITEWIDE_NOISE]
    if not candidates:
        candidates = [w for w in target_kws
                      if w not in STOPWORDS and w not in SITEWIDE_NOISE]
    if not candidates:
        # fall back to URL slug words
        slug = _tokenize(_url_slug(target_url))
        candidates = [w for w in slug
                      if w not in STOPWORDS and w not in SITEWIDE_NOISE]

    if not candidates:
        return "(write anchor)"

    # Build 2-4 word phrase
    phrase_words = []
    seen_roots = set()
    for w in candidates[:6]:
        root = w[:5]
        if root not in seen_roots:
            phrase_words.append(w.replace("-", " "))
            seen_roots.add(root)
        if len(phrase_words) == 3:
            break

    anchor = " ".join(phrase_words).title()
    return anchor if anchor else "(write anchor)"


def link_candidates(graph: dict, relate: dict, pages: list[dict],
                    page_keywords: dict | None = None,
                    max_per_page: int = 5,
                    min_relatedness: float = 0.08) -> list:
    """
    For each important page, find topically-related pages it does NOT already
    link to, with drafted anchor text.

    Ranking: 65% topical relatedness + 35% page quality.
    """
    idx200 = [p for p in pages if is_html(p) and is_200(p) and indexable(p)]

    max_inlinks   = max((_int(p.get("Unique Inlinks"), 0) for p in idx200), default=1) or 1
    max_wc        = max((_int(p.get("Word Count"), 0)     for p in idx200), default=1) or 1
    max_depth     = max((_int(p.get("Crawl Depth"), 0)    for p in idx200), default=1) or 1

    def url_penalty(url: str) -> float:
        url = url.lower()
        if "/feed/" in url:      return 0.0
        if "/page/" in url:      return 0.2
        if "/author/" in url:    return 0.3
        if "/tag/" in url:       return 0.3
        if "/category/" in url:  return 0.4
        return 1.0

    by_url = {_norm(p["Address"]): p for p in idx200}

    def page_quality(url: str) -> float:
        p = by_url.get(url)
        if not p:
            return 0.0
        wc    = min(_int(p.get("Word Count"), 0)      / max_wc,    1.0)
        inl   = min(_int(p.get("Unique Inlinks"), 0)  / max_inlinks, 1.0)
        depth = 1.0 - min(_int(p.get("Crawl Depth"), 0) / max_depth, 1.0)
        return 0.45 * wc + 0.40 * inl + 0.15 * depth

    # Pick source pages: top 60 by inlinks (covers hubs + key service pages)
    inl = {_norm(p["Address"]): _int(p.get("Unique Inlinks")) for p in idx200}
    important = sorted(inl, key=lambda u: -inl[u])[:60]

    kws = page_keywords or {}
    out = []

    for u in important:
        already = graph["out"].get(u, set())
        src_kws = kws.get(u, [])
        scored = []

        for e in relate.get(u, []):
            v = e["to"]
            rel_score = e["score"]

            if v == u or v in already:
                continue
            pen = url_penalty(v)
            if pen == 0.0:
                continue
            if rel_score < min_relatedness:
                continue

            qual = page_quality(v)
            final = (0.65 * rel_score + 0.35 * qual) * pen
            anchor = _draft_anchor(src_kws, kws.get(v, []), e["shared"], v)

            scored.append({
                "target": v,
                "relatedness": round(rel_score, 3),
                "shared_topics": e["shared"],
                "suggested_anchor": anchor,
                "_score": final,
            })

        scored.sort(key=lambda x: -x["_score"])

        candidates = []
        for c in scored[:max_per_page]:
            candidates.append({
                "target": c["target"],
                "relatedness": c["relatedness"],
                "shared_topics": c["shared_topics"],
                "suggested_anchor": c["suggested_anchor"],
            })

        if candidates:
            out.append({"source": u, "candidates": candidates})

    return out


# ---------------------------------------------------------------------------
# Orchestration entry point
# ---------------------------------------------------------------------------
def analyze(export_dir: str) -> dict:
    pages   = load_pages(export_dir)
    inlinks = load_links(export_dir, "all_inlinks.csv")
    text    = load_page_text(export_dir)

    graph   = build_graph(pages, inlinks)
    gstats  = graph_stats(pages, inlinks, graph)
    anchors = anchor_analysis(inlinks)

    clusters_result = cluster_pages(pages, text)
    idf = clusters_result.get("idf", {})

    relate = relatedness(clusters_result["page_keywords"], idf=idf)
    cands  = link_candidates(
        graph, relate, pages,
        page_keywords=clusters_result["page_keywords"]
    )

    return {
        "pages": pages,
        "graph": graph,
        "graph_stats": gstats,
        "anchors": anchors,
        "clusters": clusters_result,
        "relatedness": relate,
        "link_candidates": cands,
        "page_text_count": len(text),
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
    print(f"broken={len(g['broken_internal_links'])} "
          f"redirect={len(g['redirect_internal_links'])} "
          f"nofollow={len(g['nofollow_internal_links'])}")
    a = res["anchors"]
    print(f"generic_anchors={len(a['generic_anchors'])} empty={len(a['empty_or_image_only'])} "
          f"over_optimized={len(a['over_optimized_anchors'])}")
    cl = res["clusters"]["clusters"]
    print(f"clusters={len(cl)}  link_candidate_pages={len(res['link_candidates'])} "
          f"page_text={res['page_text_count']}")
    print("\nTop clusters:")
    for c in cl[:10]:
        print(f"  [{c['authority']:8s}] {c['name']:30s} {c['size']:3d} pages | hub: {c['hub_page']}")
    print("\nSample link candidates:")
    for rec in res["link_candidates"][:8]:
        for cand in rec["candidates"][:2]:
            print(f"  {rec['source'].split('/')[-1]!r:40s} → "
                  f"{cand['target'].split('/')[-1]!r:40s} "
                  f"anchor={cand['suggested_anchor']!r:30s} rel={cand['relatedness']}")