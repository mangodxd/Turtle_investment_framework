Convert a Markdown report to a terancejiang.com-style HTML page with intelligent data visualization.

Input: $ARGUMENTS (path to a .md file, e.g. `output/000333_美的集团/qualitative_report.md`)

---

## Task

Read the input markdown file, understand its content and structure, then generate an HTML page that matches the terancejiang.com design system. This is NOT a mechanical conversion — use your judgment to:

1. **Structure the page** with proper semantic HTML (header, nav, verdict banner, KPI cards, dimension sections, conclusion, footer)
2. **Identify data that benefits from visualization** — time-series tables, comparison tables, distribution data, etc. — and render them as Rough.js hand-drawn canvas charts alongside the original table
3. **Choose the right chart type** for each data set (bar, line, stacked bar, grouped bar, horizontal bar, etc.)
4. **Apply color semantics** — green for positive metrics, red for warnings, amber for neutral/caution
5. **Enhance readability** — use callout boxes, tags/badges, metric cards, collapsible sections where appropriate

---

## Step 1: Read the source file

Read `$ARGUMENTS` in full. Also check if a `data_pack_market.md` exists in the same directory — if so, read it too for price/market cap/industry metadata.

## Step 2: Read the design system references

Read these files to understand the exact CSS and chart patterns:

1. `~/Projects/Teracnejiang.com/assets/css/style.css` — site-wide design system (CSS variables, nav, layout)
2. `~/Projects/Teracnejiang.com/assets/css/report.css` — report-specific components (header, verdict, metrics, tables, bars, tags, callout, collapsible)
3. `~/Projects/Teracnejiang.com/assets/js/charts-report.js` — generic data-driven chart renderer for report pages (if exists)
4. `~/Projects/Teracnejiang.com/assets/js/charts-bond-etf.js` — Rough.js chart implementation patterns as reference (colors, setupCanvas, makeCoord, drawAxes, rc.rectangle, rc.path, rc.circle)
5. An existing stock report page for structural reference: `~/Projects/Teracnejiang.com/zh/stock/smic-688981-qualitative.html`

## Step 3: Ensure `charts-report.js` exists on the site

Check if `~/Projects/Teracnejiang.com/assets/js/charts-report.js` exists.

- **If it exists**: read it, understand its API, and generate HTML that uses it
- **If it does NOT exist**: create it as a generic data-driven chart renderer that all stock report pages share

### `charts-report.js` specification

This file is a **shared, reusable** chart renderer for all report pages on terancejiang.com. It reads chart data from `data-chart` JSON attributes on `<canvas>` elements and renders Rough.js hand-drawn charts.

**It must follow the exact same patterns as the site's existing chart files** (`charts-bond-etf.js`, `charts-kahneman.js`, `charts-markowitz.js`):

```javascript
/**
 * charts-report.js
 * Generic data-driven Rough.js chart renderer for report pages
 * Reads chart config from <canvas data-chart='JSON'> elements
 */
(function() {
  'use strict';

  // --- Theme detection (identical to site pattern) ---
  function isDark() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function colors() {
    var dark = isDark();
    return {
      text:      dark ? '#e8e7e0' : '#1c1c1a',
      textMuted: dark ? '#6a6a64' : '#8a8a84',
      axis:      dark ? 'rgba(255,255,255,0.25)' : 'rgba(0,0,0,0.2)',
      red:       dark ? '#e86050' : '#c0392b',
      blue:      dark ? '#5a9fd4' : '#2563a0',
      green:     dark ? '#3dbb8a' : '#1a7a5a',
      amber:     dark ? '#d4a03a' : '#a06c1a',
      gray:      dark ? '#6a6a64' : '#8a8a84',
      fill:      dark ? 'rgba(90,159,212,0.08)' : 'rgba(37,99,160,0.06)',
      bg:        dark ? '#161614' : '#fafaf7',
      greenFill: dark ? 'rgba(61,187,138,0.18)' : 'rgba(26,122,90,0.12)',
      amberFill: dark ? 'rgba(212,160,58,0.18)' : 'rgba(160,108,26,0.12)',
      redFill:   dark ? 'rgba(232,96,80,0.18)' : 'rgba(192,57,43,0.12)'
    };
  }

  // --- Canvas helpers (identical to site pattern) ---
  function dpr() { return window.devicePixelRatio || 1; }

  function setupCanvas(canvas, w, h) {
    var r = dpr();
    canvas.width = w * r;
    canvas.height = h * r;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    var ctx = canvas.getContext('2d');
    ctx.scale(r, r);
    return ctx;
  }

  // --- Core chart renderer ---
  // Reads JSON from data-chart attribute:
  // {
  //   "type": "bar" | "line" | "mixed",   (chart-level default; series can override)
  //   "labels": ["2021", "2022", "2023", "2024", "2025"],
  //   "series": [
  //     { "name": "Capex", "data": [7352, 6314, 7840, 11142], "type": "bar", "color": "blue" },
  //     { "name": "Capex/D&A", "data": [1.13, 0.86, 1.00, 1.19], "type": "line", "color": "amber", "yAxis": "right" }
  //   ],
  //   "yLeftLabel": "百万元",
  //   "yRightLabel": "倍"
  // }

  // Supports: bar, line, mixed (bar+line dual-axis), grouped-bar, horizontal-bar
  // Color names map to colors() keys: "blue", "green", "amber", "red", "gray"

  // ... rendering logic ...

  // --- Auto-init: find all canvases with data-chart and render ---
  function drawAll() { /* iterate canvases, parse JSON, render */ }

  // Redraw on theme change
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', drawAll);
  // Initial draw
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', drawAll);
  } else {
    drawAll();
  }
})();
```

**Chart style constants** (matching site aesthetic):
- Canvas size: W = 600 (responsive via max-width: 100%), H = 260-320
- Bar roughness: 1.0, line roughness: 1.2-1.5
- fillStyle: 'solid', fillWeight: 0.5, strokeWidth: 1.5
- Fonts: JetBrains Mono for data labels (11-12px), system font for axis labels (12-13px)
- Color cycle for series: [blue, green, amber, red, gray]
- Data labels above bars, dots on line data points (rc.circle, diameter 8)
- Legend: small colored swatches (rc.rectangle 10x10) with text labels
- Year labels on x-axis, value labels on y-axis

## Step 4: Generate the HTML

Write the HTML file to the same directory as the input, with `.html` extension (replace `.md`).

### Asset referencing — follow the site convention exactly

The HTML must reference external assets, **NOT** embed them inline. This is how the site works:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{company} ({code}) · 商业质量评估</title>
  <meta name="description" content="{company}（{code}）商业模式与护城河定性分析 — 6维度深度评估">
  <link rel="canonical" href="https://terancejiang.com/zh/stock/{slug}.html">
  <meta property="og:title" content="{company} ({code}) · 商业质量��估">
  <meta property="og:description" content="{company}（{code}）商业模式与护城河定性分析">
  <meta property="og:type" content="article">
  <meta property="og:url" content="https://terancejiang.com/zh/stock/{slug}.html">
  <link rel="preload" href="/assets/fonts/JetBrainsMono-Regular.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="/assets/css/style.css?v=2">
  <link rel="stylesheet" href="/assets/css/report.css?v=1">
  <style>
    /* ONLY page-specific styles here (e.g., chart-container if not in report.css) */
    .chart-container { margin: 32px 0; text-align: center; }
    .chart-container canvas { max-width: 100%; margin: 0 auto; display: block; }
    .chart-caption { font-size: 13px; color: var(--text3); margin-top: 8px; }
  </style>
</head>
<body>
  <div class="container">
    <nav class="site-nav">
      <a href="/" class="nav-logo">Terance Jiang</a>
      <div class="nav-links">
        <a href="/zh/stock/" class="active">个股研究</a>
        <a href="/zh/essays/">投资随想</a>
        <a href="/zh/sectors/">行业分析</a>
        <a href="/zh/about.html">关于</a>
      </div>
    </nav>
  </div>

  <div class="report-body">
    <!-- Header: ticker, company name, date, price, market cap -->
    <!-- Verdict banner: moat rating + one-line conclusion -->
    <!-- KPI Snapshot: 4-8 metric cards in grid -->
    <!-- Executive Summary: callout box -->
    <!-- Dimension sections: h2 with badge + content + charts -->
    <!-- Cross-verification / Deep analysis sections -->
    <!-- Conclusion section -->
    <!-- Structured parameters: collapsible details -->
    <!-- Footer: disclaimer + generation date -->
  </div>

  <!-- JS: external references, same as site convention -->
  <script src="/assets/js/rough.min.js"></script>
  <script src="/assets/js/charts-report.js"></script>
</body>
</html>
```

### Data visualization guidelines

**When to add a chart:**
- Tables with year columns (2021, 2022, ... 2025) → time-series chart
- Revenue/profit breakdown tables → horizontal bar chart or pie-like visualization
- Comparison tables (美的 vs 格力 vs 海尔) → grouped bar chart
- KPI monitoring tables (current vs threshold) �� gauge or progress bar
- Any other data where a visual would aid comprehension

**Chart type selection:**
- Absolute values over time (revenue, capex, assets) → **bar chart**
- Rates/ratios over time (ROE, margins, OCF/NI) → **line chart**
- Mixed absolute + ratio in same table → **dual-axis chart** (bars left axis, lines right axis)
- Category comparison → **grouped bar** or **horizontal bar**
- Single metric trend → **sparkline** or simple line with area fill

**HTML for each chart** (placed after the corresponding table):
```html
<div class="chart-container">
  <canvas id="chart-unique-id" data-chart='{
    "labels": ["2021", "2022", "2023", "2024", "2025"],
    "series": [
      {"name": "ROE(%)", "data": [23.58, 22.07, 22.05, 20.30, 19.98], "type": "line", "color": "blue"}
    ],
    "yLeftLabel": "%"
  }'></canvas>
  <p class="chart-caption">ROE 五年趋势</p>
</div>
```

### Content transformation rules

1. **Markdown tables** → HTML `<table>` with report.css classes. Right-align numeric columns. Use `var(--mono)` for numbers.
2. **Bold text** → `<strong>` with appropriate color (green for positive ratings, red for warnings)
3. **Rating values** (强/较强/中/弱/优秀/合格) → `<span class="tag tag-green/amber/red">` badges
4. **Blockquotes** → `<blockquote>` or `.callout` boxes for important findings
5. **Lists** → standard `<ul>/<ol>` with report.css styling
6. **Structured parameters section** → wrap in `<details><summary>` for collapsible display
7. **Checkmark items** (✓/✗) → keep as-is or enhance with colored dots

### KPI card extraction

From the structured parameters section at the end, extract key metrics for the KPI snapshot grid:
- `roe_5y_avg` → "5Y Avg ROE" card
- `moat_rating` → "护城河评级" card
- `moat_sustainability` → "可持续性" card
- `management_rating` → "管理层评价" card
- `cyclicality` → "周期性" card
- `capital_intensity` → "资本强度" card
- `entry_barrier` → "进入壁垒" card
- `moat_existence` → "优势存在性" card

Color coding: positive values (强, 优秀, 存在, 高可持续) → green highlight; negative (弱, 损害价值) → red warn; neutral (中, 中等) → amber

### Verdict banner

Extract `moat_rating` and the one-line conclusion (look for "一句话最终结论" or "一句话结论" or synthesize from 深度总结). Map to verdict color:
- 强 → green, "STRONG MOAT"
- ��强 → green, "FAIRLY STRONG"
- 中 → amber, "MODERATE"
- 弱 → red, "WEAK"

---

## Step 5: Deploy the HTML to the site project

After generating the HTML, copy it to the terancejiang.com site project:

```bash
cp output/{code}_{company}/qualitative_report.html \
   ~/Projects/Teracnejiang.com/zh/stock/{slug}.html
```

Slug naming: `{company_english}-{code}-qualitative.html` (e.g., `midea-000333-qualitative.html`)

---

## Step 6: Verify

After writing the HTML file, report:
- Output file path (both local and site copy)
- Number of sections converted
- Number of charts generated (and what type each is)
- Whether `charts-report.js` was created or already existed
- Any content that was unclear or couldn't be converted well

Open the local HTML file in the browser for the user to review.

---

## Important notes

- This is an LLM-driven conversion — use intelligence, not rigid regex. Understand the content and make good visualization decisions.
- Every chart MUST use Rough.js for the hand-drawn aesthetic. No Chart.js, no SVG-only, no CSS-only charts.
- **DO NOT embed CSS or JS inline.** Reference external files exactly like other pages on the site. The only exception is a small `<style>` block for page-specific styles (like chart-container) that don't belong in the shared CSS files.
- `charts-report.js` is a **shared site asset** at `~/Projects/Teracnejiang.com/assets/js/charts-report.js` — all report pages reference the same file. If you need to add new chart types, extend this file rather than creating per-page JS.
- Support both light and dark mode via `prefers-color-scheme` (handled by the CSS variables and charts-report.js theme detection).
- All Chinese text should be preserved as-is. Navigation links should point to terancejiang.com paths.
- Keep tables alongside charts — the chart is a visual enhancement, not a replacement for the data table.
