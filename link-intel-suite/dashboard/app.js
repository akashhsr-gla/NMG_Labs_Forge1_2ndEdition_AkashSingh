// app.js - live cockpit for the Link Intel Suite.
// Subscribes to the MCP server's SSE stream (/events) and paints KPIs,
// the graph panel, clusters and recommendations as the analysis runs.
// Falls back to polling /state if SSE drops.

const $ = (id) => document.getElementById(id);

function set(id, v) {
  const el = $(id);
  if (el) el.textContent = (v === undefined || v === null) ? "-" : v;
}

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------
function renderClusters(clusters) {
  if (!clusters || !clusters.length) {
    $("clusters").innerHTML = '<div class="empty">No clusters yet.</div>';
    set("k-clusters", 0);
    return;
  }
  set("k-clusters", clusters.length);
  $("clusters").innerHTML = clusters.map(c =>
    `<div class="cl">` +
    `<span><strong>${escHtml(c.name || c.key)}</strong> ` +
    `<span class="st">(${c.size} pages)</span></span>` +
    `<span class="tag ${c.authority}">${c.authority}</span>` +
    `</div>`
  ).join("");
}

function renderRecs(items) {
  const el = $("recs");
  if (!el) return;
  if (!items || !items.length) {
    el.innerHTML = '<div class="empty">No recommendations yet.</div>';
    return;
  }
  set("k-recs", items.length);
  el.innerHTML = items.slice(0, 60).map(r => {
    const src    = (r.source || "").replace(/https?:\/\//, "");
    const tgt    = (r.target || "").replace(/https?:\/\//, "");
    const anchor = escHtml(r.suggested_anchor || "(write anchor)");
    const rel    = typeof r.relatedness === "number"
                   ? r.relatedness.toFixed(3)
                   : (r.relatedness || "");
    const reason = escHtml(r.reason || "");
    return (
      `<div class="rec">` +
      `<span class="mono" style="font-size:11px;color:var(--mute)">${escHtml(src)}</span>` +
      ` → ` +
      `<span class="mono" style="font-size:11px">${escHtml(tgt)}</span><br>` +
      `<span class="a">↳ ${anchor}</span>` +
      (reason ? ` <span style="color:var(--mute);font-size:11px"> · ${reason}</span>` : "") +
      (rel    ? ` <span style="color:var(--mute);font-size:11px"> · rel ${rel}</span>`  : "") +
      `</div>`
    );
  }).join("");
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Full paint from RUN snapshot
// ---------------------------------------------------------------------------
function paint(RUN) {
  if (!RUN) return;
  if (RUN.site)   set("site", RUN.site);
  if (RUN.status) set("status", RUN.status);

  const g = RUN.graph_stats;
  const a = RUN.anchors;
  const e = RUN.entities;
  const s = RUN.summary;

  if (g) {
    set("k-links",  g.internal_links);
    set("k-orphans", g.orphan_pages);
    set("k-broken", g.broken_internal_links);
    set("g-pages",  g.pages_total);
    set("g-idx",    g.pages_indexable);
    set("g-depth",  g.max_crawl_depth);
    set("g-avg",    g.avg_inlinks);
    set("g-deep",   g.deepest_pages);
    set("g-under",  g.under_linked_pages);
    set("g-over",   g.over_linked_pages);
    set("g-redir",  g.redirect_internal_links);
    set("g-nofol",  g.nofollow_internal_links);
  }

  if (a) {
    set("k-generic",  a.generic);
    set("a-total",    a.total);
    set("a-generic",  a.generic);
    set("a-empty",    a.empty_or_image_only);
    set("a-over",     a.over_optimized);
  }

  if (e) set("e-pages", e.pages_with_entities);

  if (RUN.clusters)            renderClusters(RUN.clusters);

  // Recommendations: prefer the flat list stored in RUN, fall back to count
  if (RUN.link_recommendations && RUN.link_recommendations.length) {
    renderRecs(RUN.link_recommendations);
  } else if (s && s.link_recommendations) {
    set("k-recs", s.link_recommendations);
  } else if (typeof RUN.recommendations === "number") {
    set("k-recs", RUN.recommendations);
  }
}

// ---------------------------------------------------------------------------
// Live event feed
// ---------------------------------------------------------------------------
function feed(line) {
  const f = $("feed");
  if (!f) return;
  const d = document.createElement("div");
  d.textContent = "[" + new Date().toLocaleTimeString() + "] " + line;
  f.prepend(d);
  while (f.childNodes.length > 80) f.removeChild(f.lastChild);
}

// ---------------------------------------------------------------------------
// SSE event handlers
// ---------------------------------------------------------------------------
let RUN = {};

function onEvent(evt) {
  const { event, data } = evt;

  if (event === "snapshot") {
    RUN = data || {};
    paint(RUN);
    feed("connected");
    return;
  }

  if (event === "loaded") {
    RUN.site   = data.site;
    RUN.urls   = data.urls;
    RUN.status = "running";
    set("site", RUN.site);
    set("status", RUN.status);
    feed(`loaded ${data.urls} pages · ${data.page_text} page texts`);
  }

  if (event === "graph") {
    RUN.graph_stats = data;
    feed(`graph · ${data.orphan_pages} orphans · ${data.broken_internal_links} broken`);
    paint(RUN);
  }

  if (event === "anchors") {
    RUN.anchors = data;
    feed(`anchors · ${data.generic} generic · ${data.empty_or_image_only} empty`);
    paint(RUN);
  }

  if (event === "topics") {
    RUN.clusters = data.clusters;
    feed(`topics · ${data.clusters.length} clusters`);
    renderClusters(RUN.clusters);
  }

  if (event === "entities") {
    RUN.entities = data;
    feed(`entities on ${data.pages_with_entities} pages`);
    set("e-pages", data.pages_with_entities);
  }

  if (event === "recommendations") {
    // data.items is the flat array; data.count is the total
    RUN.recommendations = data.count;
    if (data.items && data.items.length) {
      RUN.link_recommendations = data.items;
      renderRecs(data.items);
    } else {
      set("k-recs", data.count);
    }
    feed(`${data.count} link recommendations ready`);
  }

  if (event === "saved") {
    RUN.status = "done";
    set("status", "done");
    feed("report.json written ✓");
  }

  if (event === "exported") {
    feed("report.html exported ✓");
  }
}

// ---------------------------------------------------------------------------
// Connection management
// ---------------------------------------------------------------------------
function connect() {
  try {
    const es = new EventSource("/events");
    es.onmessage = (m) => {
      try { onEvent(JSON.parse(m.data)); } catch (err) { /* ignore parse errors */ }
    };
    es.onerror = () => {
      es.close();
      feed("SSE dropped – polling…");
      setTimeout(poll, 1500);
    };
  } catch (err) {
    poll();
  }
}

function poll() {
  fetch("/state")
    .then(r => r.json())
    .then(d => { RUN = d; paint(RUN); })
    .catch(() => {});
  setTimeout(poll, 3000);
}

connect();