# Forge 1 (Edition 2) - Internal Linking Intelligence - Starter Bundle

Everything you need to build the challenge in 6 hours.

- `link-intel-suite/`  - the starter Claude Code plugin (skill + 5 sub-agents + local MCP
  server + live dashboard + a deterministic analyzer with TODOs + run.py). Plumbing works
  out of the box; you implement the analysis and push accuracy.
- `sample-export/`     - a real Screaming Frog crawl of nmgtechnologies.com:
  `internal_html.csv` (+ `internal_all.csv` alias), `all_inlinks.csv`, `all_outlinks.csv`,
  `all_anchor_text.csv`, and `page text/` (full body text per page).
- `rulebook.md`        - the exact analysis definitions (graph, anchors, topics, entity
  graph, contextual link recommendations).
- `report.schema.json` - the `report.json` output contract.

## Run it
```bash
cd link-intel-suite
pip install -r ../requirements.txt
pip install mcp
python run.py ../sample-export/
# live cockpit: http://localhost:7700
# outputs: link-intel-suite/outputs/report.{json,html,pdf,pptx}
```

## Export Formats

The analyzer now generates professional reports in three formats:

- **report.html** - Interactive HTML dashboard
- **report_[domain].pdf** - Print-ready PDF report (WeasyPrint)
- **report_[domain].pptx** - PowerPoint presentation (python-pptx)

See [EXPORTERS.md](EXPORTERS.md) for full documentation on PDF/PPTX export features and customization.

## Model fairness (8 GB laptops welcome)
You may use Ollama free **cloud** models (e.g. `gpt-oss:20b-cloud`, `gemma3:27b-cloud`,
`qwen3-coder:480b-cloud`, `deepseek-v3.1:671b-cloud`) or **local** models (`qwen3:8b`,
`gemma3:12b`). Cloud models may not write a local `.claude/audit.jsonl` - that is fine, the
audit log is NOT mandatory. Process is judged from git history + the manually-kept
`PROMPTS.md` / `DECISIONS.md`, and the result from the working plugin + reproducible
`report.json`. See `link-intel-suite/README.md` for the full note.
