# PROMPTS.md

## Prompt 1

**Prompt:**
"Analyze linkintel/analyzer.py.

Improve GENERIC_ANCHORS.

Add sensible generic anchor variants:

* read here
* learn here
* visit page
* explore more
* check this out
* get started
* see also
* read full article
* click for more

Do not modify any other logic.

Show me the diff before applying."

**For:**
Improving detection of generic anchor text patterns for the anchor audit section.

**Revised?**
No. Applied directly after reviewing the diff.

---

## Prompt 2

**Prompt:**
"Modify ONLY the function link_candidates() in linkintel/analyzer.py.

Do NOT modify:

* cluster_pages()
* relatedness()
* anchor_analysis()
* graph_stats()
* any other file

Current problem:
The recommendation engine ranks pages only using:

1. Unique Inlinks
2. Keyword-overlap relatedness

Goal:
Improve recommendation quality using deterministic page-quality scoring based on data already available in internal_html.csv.

Available columns:

* Word Count
* Unique Inlinks
* Link Score
* Crawl Depth

Requirements:

1. Create a page-quality scoring system.
2. Rank candidates using:
   final_score = 0.7 * relatedness + 0.3 * quality
3. Keep output schema unchanged.
4. Do not modify report.json schema.
5. Show diff before applying."

**For:**
Improving contextual internal-link recommendation ranking using authority and content metrics rather than relatedness alone.

**Revised?**
Yes. Removed dependence on Semantic Relevance Score and moved to fully deterministic crawl metrics after testing.
