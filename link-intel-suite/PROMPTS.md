# PROMPTS.md

## Prompt 1 — Expand Generic Anchor Detection

### Prompt

Analyze `linkintel/analyzer.py`.

Modify ONLY the `GENERIC_ANCHORS` set.

Add sensible generic anchor variants commonly found in internal linking audits, including:

* read here
* learn here
* visit page
* explore more
* check this out
* get started
* see also
* read full article
* click for more

Requirements:

* Do not modify any other logic.
* Do not change any functions.
* Do not alter output schemas.
* Show the diff before applying changes.

### Purpose

Improve detection of weak or non-descriptive anchor text during anchor audits.

### Result

Expanded generic anchor coverage without affecting any other analyzer behavior.

---

## Prompt 2 — Deterministic Recommendation Quality Scoring

### Prompt

Modify ONLY the function `link_candidates()` in `linkintel/analyzer.py`.

Do NOT modify:

* `cluster_pages()`
* `relatedness()`
* `anchor_analysis()`
* `graph_stats()`
* any other function
* any other file

Current problem:

Recommendations are ranked primarily by keyword overlap and inlink counts.

Goal:

Improve recommendation quality using deterministic page-quality scoring derived from crawl data already available in `internal_html.csv`.

Available signals:

* Word Count
* Unique Inlinks
* Link Score
* Crawl Depth

Requirements:

1. Build a page-quality score using available crawl metrics.
2. Compute:
   `final_score = 0.70 * relatedness + 0.30 * quality`
3. Preserve existing output schema.
4. Do not change `report.json` structure.
5. Show the diff before applying changes.

### Purpose

Increase recommendation quality by favoring authoritative, content-rich pages rather than relying solely on topical overlap.

### Result

More useful internal-link recommendations with deterministic ranking.

---

## Prompt 3 — TF-IDF Keyword Extraction Upgrade

### Prompt

Analyze `page_keywords()` in `linkintel/analyzer.py`.

Current issue:

Keyword extraction relies heavily on raw term frequency, causing cluster labels such as:

* Apps
* Hire
* Outsource
* Similar
* Years

instead of meaningful topical labels.

Upgrade the keyword extraction system while remaining fully deterministic.

Requirements:

1. Replace TF-only scoring with TF-IDF scoring.
2. Build sitewide document frequencies once and reuse them.
3. Weight sources differently:

   * Title = 6x
   * H1 = 5x
   * H2 = 3x
   * H3 = 2x
   * Body = 1x
4. Ignore stopwords and sitewide-noise terms.
5. Remove weak keywords:

   * length < 4
   * non-alphabetic tokens
6. Preserve deterministic behavior.
7. Do not introduce external dependencies.
8. Show diff before applying.

### Purpose

Generate higher-quality topical keywords for clustering and recommendation explanations.

### Result

Cluster names become more meaningful and topic-focused.

---

## Prompt 4 — Semantic Topic Clustering

### Prompt

Analyze `cluster_pages()` in `linkintel/analyzer.py`.

Current issue:

Clusters are dominated by URL structure and generic keywords, producing labels such as:

* Apps
* Blog
* Hire
* Outsource

Goal:

Move from path-based clustering to semantic topic clustering.

Requirements:

1. Create a deterministic topic vocabulary system.
2. Assign pages to topics using:

   * TF-IDF keywords
   * URL slug terms
3. Support categories such as:

   * Mobile
   * Web
   * AI
   * Cloud
   * Healthcare
   * FinTech
   * eCommerce
   * Design
   * ERP
   * Analytics
   * Security
   * Outsourcing
4. Merge tiny clusters into "Other".
5. Keep cluster output schema unchanged.
6. Preserve deterministic execution.
7. Show diff before applying.

### Purpose

Produce meaningful topical authority clusters.

### Result

Cluster names become:

* Mobile App Development
* AI & Machine Learning
* Cloud & DevOps
* eCommerce
* Healthcare

instead of generic labels.

---

## Prompt 5 — Cosine TF-IDF Relatedness

### Prompt

Analyze `relatedness()` in `linkintel/analyzer.py`.

Current issue:

Relatedness uses simple Jaccard overlap, which treats all keywords equally.

Goal:

Upgrade page similarity scoring using TF-IDF-weighted cosine similarity.

Requirements:

1. Use keyword vectors weighted by IDF.
2. Compute cosine similarity.
3. Preserve existing output schema:

   * to
   * score
   * shared
4. Keep implementation deterministic.
5. Do not introduce external libraries.
6. Show diff before applying.

### Purpose

Improve topical matching quality.

### Result

Rare and meaningful keywords contribute more than generic shared terms.

---

## Prompt 6 — Recommendation Rendering Fix (Server + Dashboard)

### Prompt

Fix recommendation rendering in the Link Intel Suite.

Files allowed:

* `mcp/server.py`
* `dashboard/app.js`

Do not modify any other file.

Problems:

1. Recommendations are generated but never pushed after `li_load()`.
2. SSE payload contains only counts, not recommendation objects.
3. Dashboard never renders recommendation items from snapshots.

Requirements:

### Server

* Add `_flatten_candidates()`
* Add `_auto_push_recommendations()`
* Populate:

  * `_A["final_recs"]`
  * `RUN["link_recommendations"]`
  * `RUN["recommendations"]`
* Emit:

  ```python
  {
      "count": N,
      "items": [...]
  }
  ```
* Auto-push recommendations after load.

### Dashboard

* Add `renderRecs()`
* Add `escHtml()`
* Render recommendation list from:

  * SSE updates
  * Snapshot state
* Keep KPI counters working.

Constraints:

* Do not change function signatures.
* Do not modify analyzer.py.
* Show diff before applying.

### Purpose

Make recommendations visible immediately after analysis completes.

### Result

Dashboard shows recommendation cards with:

* Source URL
* Target URL
* Suggested anchor
* Relatedness score
* Recommendation reason

without requiring an AI agent.
