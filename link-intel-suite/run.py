#!/usr/bin/env python3
"""
run.py - headless runner for the Link Intel Suite (also the grader's entry point).

Runs the full internal-linking analysis on a Screaming Frog export with no Claude Code:
  load -> graph -> anchors -> topics -> entities (TF proxy) -> recommend (candidates)
       -> write report.json + report.html + report.pdf + report.pptx

Usage:
  python run.py sample-export/
  python run.py sample-export/ --no-dashboard
  python run.py sample-export/ --verbose

The model-driven steps (cluster naming, entity extraction, writing the contextual link
anchors) are left as build TODOs; the starter writes deterministic placeholders so the
report.json contract stays valid and the pipeline always produces a graded artifact.
"""
from __future__ import annotations
import argparse, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "mcp"))
sys.path.insert(0, HERE)
import server  # the MCP server module exposes every tool as a function


def main():
    ap = argparse.ArgumentParser(description="Link Intel Suite - Headless Analysis Runner")
    ap.add_argument("export_dir", help="Path to Screaming Frog export directory")
    ap.add_argument("--no-dashboard", action="store_true", help="Skip dashboard server")
    ap.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = ap.parse_args()

    # Start dashboard if requested
    if not args.no_dashboard:
        try:
            server.start_dashboard()
            print(f"🌐 Dashboard: http://localhost:{server.PORT}", flush=True)
            time.sleep(0.5)
        except Exception as e:
            print(f"⚠️  Dashboard startup failed (continuing headless): {e}")

    try:
        t0 = time.time()
        
        if args.verbose:
            print("🔍 Running analysis pipeline...\n")
        
        # Run full pipeline
        server.li_load(args.export_dir)
        server.li_graph()
        server.li_anchors()
        server.li_topics()        # no model names in headless mode (cluster keys used)
        server.li_entities()      # uses TF-keyword relatedness proxy
        # Starter does NOT attach model-written recs; _report_obj() then falls back to the
        # deterministic candidates (no anchors) so the contract always has data to grade.
        server.RUN["model_calls"] = 0
        elapsed = time.time() - t0
        server.RUN["duration_sec"] = round(elapsed, 2)
        
        if args.verbose:
            print(f"\n✅ Analysis complete in {elapsed:.2f}s\n")
        
        # Generate reports
        server.li_report()
        server.li_export()

        # Summary output
        s = server.RUN["summary"]
        print("\n" + "="*50)
        print("📊 INTERNAL LINKING INTELLIGENCE REPORT")
        print("="*50)
        print(f"Site              : {server.RUN['site']}  ({s['pages_crawled']} pages)")
        print(f"Internal links    : {s['internal_links']:,}")
        print(f"Avg inlinks/page  : {s['avg_inlinks']}")
        print(f"Crawl depth       : {s['max_crawl_depth']}")
        print()
        print(f"⚠️  Issues Found")
        print(f"  Orphan pages        : {s['orphan_pages']}")
        print(f"  Broken internal     : {s['broken_internal_links']}")
        print(f"  Generic anchors     : {s['generic_anchors']}")
        print(f"  Over-optimized      : {s['over_optimized_anchors']}")
        print()
        print(f"🏷️  Topical Analysis")
        print(f"  Clusters identified : {s['topical_clusters']}")
        print()
        print(f"🔗 Recommendations")
        print(f"  Link suggestions    : {s['link_recommendations']}")
        print()
        print(f"📁 Outputs")
        print(f"  ✓ outputs/report.json   (raw analysis data)")
        print(f"  ✓ outputs/report.html   (interactive dashboard)")
        
        # Check for PDF/PPTX
        domain = server.RUN.get("site", "website").replace(".", "_")
        pdf_path = os.path.join(server.OUT_DIR, f"report_{domain}.pdf")
        pptx_path = os.path.join(server.OUT_DIR, f"report_{domain}.pptx")
        
        if os.path.exists(pdf_path):
            print(f"  ✓ outputs/report_{domain}.pdf   (professional PDF report)")
        if os.path.exists(pptx_path):
            print(f"  ✓ outputs/report_{domain}.pptx  (PowerPoint presentation)")
        
        print()
        print(f"⏱️  Performance: {elapsed:.2f}s")
        print("="*50 + "\n")
        
        return 0
        
    except FileNotFoundError as e:
        print(f"\n❌ Error: {e}")
        print(f"\nExpected files in {args.export_dir}:")
        print("  - internal_html.csv or internal_all.csv")
        print("  - all_inlinks.csv")
        print("  - page text/ (directory)")
        return 1
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
