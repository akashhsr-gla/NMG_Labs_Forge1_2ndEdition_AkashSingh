"""
server.py - local MCP server + live dashboard host (one process, two faces).

  1. MCP tools over stdio  -> Claude Code calls: li_load, li_graph, li_anchors,
     li_topics, li_entities, li_recommend, li_report, li_export
  2. HTTP + SSE on localhost:7700 -> the live cockpit that fills as the analysis runs.

FIX: link_candidates are now surfaced to the dashboard automatically after li_load
     (no model agent required). The "recommendations" event is emitted with the
     deterministic candidates so the cockpit always shows something useful.
     When li_set_recommendations() is later called by a model agent it overwrites
     them with richer anchor text / reasons.
"""
from __future__ import annotations
import json, os, queue, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DASH_DIR = os.path.join(ROOT, "dashboard")
OUT_DIR  = os.path.join(ROOT, "outputs")
PORT  = int(os.environ.get("LI_PORT", os.environ.get("SEO_PORT", "7700")))
MODEL = os.environ.get("RADAR_MODEL", os.environ.get("LI_MODEL", "gpt-oss:20b-cloud"))

import sys
sys.path.insert(0, ROOT)
from linkintel import analyzer  # noqa: E402

RUN: dict = {
    "site": None, "urls": 0, "status": "idle",
    "graph_stats": None, "anchors": None, "clusters": None,
    "entities": None, "recommendations": None, "summary": None,
    # NEW: flat list of recommendation dicts for the dashboard
    "link_recommendations": [],
}
_A: dict = {}          # full analysis blob (kept out of RUN so /state stays light)
_subs: list[queue.Queue] = []
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------
def _emit(event: str, data):
    payload = json.dumps({"event": event, "data": data})
    with _lock:
        for q in list(_subs):
            try:
                q.put_nowait(payload)
            except Exception:
                pass


def _site(pages) -> str:
    if not pages:
        return "unknown"
    try:
        return urlparse(pages[0].get("Address", "")).netloc or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _flatten_candidates(link_candidates: list) -> list[dict]:
    """Convert link_candidates blobs → flat list of recommendation dicts."""
    out = []
    for blk in link_candidates:
        for c in blk["candidates"]:
            out.append({
                "source": blk["source"],
                "target": c["target"],
                "suggested_anchor": c.get("suggested_anchor") or "(write anchor)",
                "relatedness": c["relatedness"],
                "reason": "shared topics: " + ", ".join(c.get("shared_topics") or []),
            })
    return out


# ---------------------------------------------------------------------------
# Pipeline tools (importable by run.py without MCP)
# ---------------------------------------------------------------------------
def li_load(export_dir: str) -> dict:
    res = analyzer.analyze(export_dir)
    _A.clear()
    _A.update(res)

    site = _site(res["pages"])
    RUN.update({
        "urls": res["graph_stats"]["pages_total"],
        "site": site,
        "status": "running",
        "page_text_count": res["page_text_count"],
    })
    _emit("loaded", {"site": site, "urls": RUN["urls"],
                     "page_text": res["page_text_count"]})

    # ── Auto-populate graph, anchors, topics, and recommendations ──────────
    # This means the dashboard fills completely from a single li_load() call
    # without needing a model agent to drive each step.
    li_graph()
    li_anchors()
    li_topics()
    _auto_push_recommendations()
    # ───────────────────────────────────────────────────────────────────────

    return {"urls": RUN["urls"], "site": site, "page_text": res["page_text_count"]}


def _auto_push_recommendations():
    """Push the deterministic link candidates to the dashboard immediately."""
    cands = _A.get("link_candidates", [])
    flat  = _flatten_candidates(cands)
    _A["final_recs"] = flat                    # make li_report() pick them up
    RUN["recommendations"]      = len(flat)
    RUN["link_recommendations"] = flat         # dashboard reads this via /state
    _emit("recommendations", {
        "count": len(flat),
        "items": flat,                         # app.js renders these directly
    })


def li_graph() -> dict:
    g = _A["graph_stats"]
    RUN["graph_stats"] = {
        "pages_total":            g["pages_total"],
        "pages_indexable":        g["pages_indexable"],
        "internal_links":         g["internal_links"],
        "max_crawl_depth":        g["max_crawl_depth"],
        "avg_inlinks":            g["avg_inlinks"],
        "orphan_pages":           len(g["orphan_pages"]),
        "deepest_pages":          len(g["deepest_pages"]),
        "under_linked_pages":     len(g["under_linked_pages"]),
        "over_linked_pages":      len(g["over_linked_pages"]),
        "broken_internal_links":  len(g["broken_internal_links"]),
        "redirect_internal_links":len(g["redirect_internal_links"]),
        "nofollow_internal_links":len(g["nofollow_internal_links"]),
    }
    _emit("graph", RUN["graph_stats"])
    return RUN["graph_stats"]


def li_anchors() -> dict:
    a = _A["anchors"]
    RUN["anchors"] = {
        "generic":          len(a["generic_anchors"]),
        "empty_or_image_only": len(a["empty_or_image_only"]),
        "over_optimized":   len(a["over_optimized_anchors"]),
        "total":            a["total_internal_anchors"],
    }
    _emit("anchors", RUN["anchors"])
    return RUN["anchors"]


def li_topics(names: dict = None) -> dict:
    """Compute clusters; `names` (optional) is {cluster_key: model_chosen_name}."""
    cl = _A["clusters"]["clusters"]
    if names:
        for c in cl:
            if c["key"] in names:
                c["name"] = names[c["key"]]
    RUN["clusters"] = [
        {
            "key":       c["key"],
            "name":      c["name"],
            "size":      c["size"],
            "hub_page":  c["hub_page"],
            "authority": c["authority"],
            "keywords":  c["keywords"],
        }
        for c in cl
    ]
    _emit("topics", {"clusters": RUN["clusters"]})
    return {"clusters": len(cl)}


def li_entities(entities: dict = None) -> dict:
    """Attach model-extracted entities per page: {url: [entity, ...]}.
    If provided, rebuilds the relatedness graph and refreshes candidates.
    """
    if entities:
        _A["entities"] = entities
        idf = _A["clusters"].get("idf", {})
        _A["relatedness"] = analyzer.relatedness(entities, idf=idf)
        _A["link_candidates"] = analyzer.link_candidates(
            _A["graph"], _A["relatedness"], _A["pages"],
            page_keywords=entities,
        )
        # Re-push updated recommendations
        _auto_push_recommendations()

    RUN["entities"] = {"pages_with_entities": len(_A.get("entities") or {})}
    _emit("entities", RUN["entities"])
    return RUN["entities"]


def li_set_recommendations(recommendations: list) -> dict:
    """Attach the final contextual link recommendations written by the linker-agent.

    Each item: {source, target, suggested_anchor, relatedness, reason}.
    Overwrites the deterministic candidates with richer model-written anchors.
    """
    _A["final_recs"]            = recommendations or []
    RUN["recommendations"]      = len(_A["final_recs"])
    RUN["link_recommendations"] = _A["final_recs"]
    _emit("recommendations", {
        "count": RUN["recommendations"],
        "items": _A["final_recs"],
    })
    return {"count": RUN["recommendations"]}


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------
def _report_obj() -> dict:
    g   = _A["graph_stats"]
    a   = _A["anchors"]
    cl  = _A["clusters"]["clusters"]
    recs = _A.get("final_recs") or _flatten_candidates(_A.get("link_candidates", []))

    summary = {
        "pages_crawled":         g["pages_total"],
        "indexable_pages":       g["pages_indexable"],
        "internal_links":        g["internal_links"],
        "orphan_pages":          len(g["orphan_pages"]),
        "broken_internal_links": len(g["broken_internal_links"]),
        "generic_anchors":       len(a["generic_anchors"]),
        "topical_clusters":      len(cl),
        "link_recommendations":  len(recs),
    }
    RUN["summary"] = summary
    return {
        "site":         RUN["site"],
        "pages_crawled":g["pages_total"],
        "summary":      summary,
        "link_graph": {
            "internal_links":          g["internal_links"],
            "max_crawl_depth":         g["max_crawl_depth"],
            "avg_inlinks":             g["avg_inlinks"],
            "orphan_pages":            g["orphan_pages"],
            "deepest_pages":           g["deepest_pages"],
            "under_linked_pages":      g["under_linked_pages"],
            "over_linked_pages":       g["over_linked_pages"],
            "broken_internal_links":   g["broken_internal_links"],
            "redirect_internal_links": g["redirect_internal_links"],
            "nofollow_internal_links": g["nofollow_internal_links"],
        },
        "anchor_text": {
            "total_internal_anchors":  a["total_internal_anchors"],
            "generic_anchors":         a["generic_anchors"],
            "empty_or_image_only":     a["empty_or_image_only"],
            "over_optimized_anchors":  a["over_optimized_anchors"],
        },
        "topical_clusters": [
            {
                "key":        c["key"],
                "name":       c["name"],
                "size":       c["size"],
                "pages":      c["pages"],
                "hub_page":   c["hub_page"],
                "hub_inlinks":c["hub_inlinks"],
                "authority":  c["authority"],
                "keywords":   c["keywords"],
            }
            for c in cl
        ],
        "entity_graph":       _A.get("relatedness", {}),
        "link_recommendations": recs,
        "run_meta": {
            "model":       MODEL,
            "model_calls": RUN.get("model_calls", 0),
            "duration_sec":RUN.get("duration_sec", 0),
        },
    }


def li_report() -> dict:
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "report.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(_report_obj(), f, indent=2)
    RUN["status"] = "done"
    _emit("saved", {"path": p})
    return {"path": p}


def li_export() -> dict:
    """Export analysis results to all formats (HTML, PDF, PPTX).
    
    Emits SSE event with export status and paths.
    Falls back gracefully if PDF/PPTX libraries not available.
    """
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # Export HTML (existing)
    try:
        p_html = os.path.join(OUT_DIR, "report.html")
        with open(p_html, "w", encoding="utf-8") as f:
            f.write(_render_html(_report_obj()))
        _emit("export_progress", {"format": "html", "status": "complete", "path": p_html})
    except Exception as e:
        print(f"❌ HTML export failed: {e}")
        _emit("export_progress", {"format": "html", "status": "error", "error": str(e)})
        p_html = None
    
    # Export PDF and PPTX (new)
    try:
        from linkintel import exporters
        domain = RUN.get("site", "website.com") or "website.com"
        
        _emit("export_progress", {"format": "pdf_pptx", "status": "starting"})
        exports = exporters.export_results(_A, OUT_DIR, domain, ["pdf", "pptx"], verbose=False)
        
        p_pdf = os.path.join(OUT_DIR, f"report_{domain.replace('.', '_')}.pdf") if exports.get("pdf") else None
        p_pptx = os.path.join(OUT_DIR, f"report_{domain.replace('.', '_')}.pptx") if exports.get("pptx") else None
        
        if exports.get("pdf"):
            _emit("export_progress", {"format": "pdf", "status": "complete", "path": p_pdf})
        else:
            _emit("export_progress", {"format": "pdf", "status": "skipped", "reason": "export_failed"})
            
        if exports.get("pptx"):
            _emit("export_progress", {"format": "pptx", "status": "complete", "path": p_pptx})
        else:
            _emit("export_progress", {"format": "pptx", "status": "skipped", "reason": "export_failed"})
        
        _emit("exported", {
            "html": p_html,
            "pdf": p_pdf,
            "pptx": p_pptx,
            "formats": {
                "pdf": exports.get("pdf", False),
                "pptx": exports.get("pptx", False),
            }
        })
        
        return {
            "html": p_html,
            "pdf": p_pdf,
            "pptx": p_pptx,
            "formats": exports
        }
    except ImportError as e:
        print(f"⚠️  Export library not available: {e}")
        _emit("export_progress", {"format": "pdf_pptx", "status": "skipped", "reason": "library_not_installed"})
        _emit("exported", {"html": p_html, "pdf": None, "pptx": None})
        return {"html": p_html, "pdf": None, "pptx": None, "formats": {"pdf": False, "pptx": False}}
    except Exception as e:
        print(f"❌ PDF/PPTX export failed: {e}")
        _emit("export_progress", {"format": "pdf_pptx", "status": "error", "error": str(e)})
        _emit("exported", {"html": p_html, "pdf": None, "pptx": None})
        return {"html": p_html, "pdf": None, "pptx": None, "formats": {"pdf": False, "pptx": False}}


def _render_html(o) -> str:
    s = o["summary"]
    cl_rows = "".join(
        f'<tr><td>{c.get("name") or c["key"]}</td><td>{c["size"]}</td>'
        f'<td><span class="sev {"high" if c["authority"] == "hub" else "low"}">'
        f'{c["authority"]}</span></td>'
        f'<td class="mono" style="font-size:11px">'
        f'{(c["hub_page"] or "").replace("https://", "")}</td></tr>'
        for c in o["topical_clusters"]
    )
    rec_rows = "".join(
        f'<tr>'
        f'<td class="mono" style="font-size:11px">{r["source"].replace("https://", "")}</td>'
        f'<td class="mono" style="font-size:11px">{r["target"].replace("https://", "")}</td>'
        f'<td><strong>{r.get("suggested_anchor") or "(write anchor)"}</strong></td>'
        f'<td>{r.get("relatedness", "")}</td>'
        f'</tr>'
        for r in o["link_recommendations"][:40]
    )
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Internal Linking Intelligence - {o['site']}</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;background:#1a1a1f;color:#f8f7f4;margin:0;padding:40px;line-height:1.5}}
.wrap{{max-width:920px;margin:0 auto}}h1{{font-size:28px;margin:0 0 4px}}
.sub{{color:#c8c5be;margin-bottom:24px}}
.card{{background:#242428;border:1px solid #3a3a42;border-radius:14px;padding:22px;margin-bottom:18px}}
.k{{display:flex;gap:22px;flex-wrap:wrap}}
.k div{{font-size:13px;color:#c8c5be}}.k b{{display:block;font-size:28px;color:#f8f7f4}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid #3a3a42}}
th{{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:#c8c5be}}
.mono{{font-family:'JetBrains Mono',ui-monospace,monospace}}
.sev{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px}}
.sev.high{{background:#22c55e;color:#04210f}}.sev.low{{background:#3a3a42;color:#c8c5be}}
.muted{{color:#c8c5be;font-size:13px}}
</style></head><body><div class="wrap">
<h1>Internal Linking Intelligence</h1>
<div class="sub">{o['site']} - {o['pages_crawled']} pages crawled</div>
<div class="card k">
  <div><b>{s['internal_links']}</b>internal links</div>
  <div><b style="color:#e2b53e">{s['orphan_pages']}</b>orphan pages</div>
  <div><b style="color:#FF0000">{s['broken_internal_links']}</b>broken internal links</div>
  <div><b>{s['generic_anchors']}</b>generic anchors</div>
  <div><b>{s['topical_clusters']}</b>clusters</div>
  <div><b style="color:#6ea8fe">{s['link_recommendations']}</b>link suggestions</div>
</div>
<div class="card"><h3>Topical clusters &amp; authority</h3>
  <table><thead><tr><th>Cluster</th><th>Pages</th><th>Authority</th><th>Hub page</th></tr></thead>
  <tbody>{cl_rows or '<tr><td colspan=4 class=muted>No clusters.</td></tr>'}</tbody></table>
</div>
<div class="card"><h3>Contextual internal link recommendations</h3>
  <table><thead><tr><th>From</th><th>Should link to</th><th>Suggested anchor</th><th>Rel.</th></tr></thead>
  <tbody>{rec_rows or '<tr><td colspan=4 class=muted>No recommendations.</td></tr>'}</tbody></table>
</div>
<p class="muted">Generated by Link Intel Suite - model {o.get('run_meta', {}).get('model', '')}</p>
</div></body></html>"""


# ---------------------------------------------------------------------------
# Dashboard HTTP host
# ---------------------------------------------------------------------------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body.encode() if isinstance(body, str) else body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            p = os.path.join(DASH_DIR, "index.html")
            self._send(200, open(p, encoding="utf-8").read()
                       if os.path.exists(p) else "no dashboard")

        elif self.path == "/app.js":
            p = os.path.join(DASH_DIR, "app.js")
            self._send(200, open(p, encoding="utf-8").read()
                       if os.path.exists(p) else "", "application/javascript")

        elif self.path == "/state":
            self._send(200, json.dumps(RUN), "application/json")

        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q: queue.Queue = queue.Queue()
            with _lock:
                _subs.append(q)
            try:
                snapshot = json.dumps({"event": "snapshot", "data": RUN})
                self.wfile.write(f"data: {snapshot}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        msg = q.get(timeout=15)
                        self.wfile.write(f"data: {msg}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                with _lock:
                    if q in _subs:
                        _subs.remove(q)

        else:
            self._send(404, "not found")


def start_dashboard(port=PORT):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------
def _run_mcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print(f"[li] MCP SDK not found. Dashboard only at http://localhost:{PORT}",
              flush=True)
        while True:
            time.sleep(3600)

    mcp = FastMCP("link-intel-suite")

    @mcp.tool()
    def load(export_dir: str) -> dict:
        """Load a Screaming Frog export (internal_html.csv + all_inlinks.csv + page text/).
        Also auto-runs graph, anchors, topics and pushes deterministic link candidates."""
        return li_load(export_dir)

    @mcp.tool()
    def graph_stats() -> dict:
        """Run the deterministic internal-link graph analysis (orphans, depth, broken/redirect/nofollow)."""
        return li_graph()

    @mcp.tool()
    def anchors() -> dict:
        """Run anchor-text analysis (generic, empty/image-only, over-optimized)."""
        return li_anchors()

    @mcp.tool()
    def topics(names: dict = None) -> dict:
        """Compute topical clusters; optionally attach model-chosen cluster names {key:name}."""
        return li_topics(names)

    @mcp.tool()
    def entities(entities: dict = None) -> dict:
        """Attach model-extracted entities per page {url:[entity,...]} and rebuild the entity graph."""
        return li_entities(entities)

    @mcp.tool()
    def recommend(recommendations: list) -> dict:
        """Attach final contextual link recommendations [{source,target,suggested_anchor,relatedness,reason}].
        Overwrites the deterministic candidates with model-written anchors."""
        return li_set_recommendations(recommendations)

    @mcp.tool()
    def write_report() -> dict:
        """Write outputs/report.json (the grader reads this)."""
        return li_report()

    @mcp.tool()
    def export_report() -> dict:
        """Write outputs/report.html (the client deliverable)."""
        return li_export()

    mcp.run()


if __name__ == "__main__":
    start_dashboard()
    print(f"[li] dashboard live at http://localhost:{PORT}", flush=True)
    _run_mcp()