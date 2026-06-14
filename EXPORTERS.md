# PDF & PPTX Export Guide

The Link Intel Suite now supports professional PDF and PPTX export of analysis results.

## Installation

```bash
# Install export dependencies
pip install -r requirements.txt

# Or install individually:
pip install WeasyPrint python-pptx
```

## Features

### PDF Export (WeasyPrint)
- ✅ Professional, print-ready PDF reports
- ✅ Automatic page breaks for long content
- ✅ Responsive styling with metrics cards
- ✅ Clean typography with proper spacing
- ✅ Page numbering and footers
- ✅ Full-color visualizations

**Output:** `report_[domain].pdf`

### PPTX Export (python-pptx)
- ✅ Professional PowerPoint presentations
- ✅ 7+ slides with content sections
- ✅ Color-coded severity badges
- ✅ Executive summary with key metrics
- ✅ Topical clusters overview
- ✅ Strategic recommendations
- ✅ Link recommendations with suggested anchors

**Output:** `report_[domain].pptx`

## Usage

### Via Command Line

```bash
# Full analysis with all exports (HTML, PDF, PPTX)
python run.py sample-export/

# This will generate:
# - outputs/report.html
# - outputs/report_example_com.pdf
# - outputs/report_example_com.pptx
```

### Programmatic Usage

```python
from linkintel import analyzer, exporters

# Run analysis
result = analyzer.analyze("sample-export/")

# Export to specific formats
exports = exporters.export_results(
    result,
    output_dir="outputs",
    domain="example.com",
    formats=["pdf", "pptx"]
)

# Check results
if exports["pdf"]:
    print("✅ PDF created successfully")
if exports["pptx"]:
    print("✅ PPTX created successfully")
```

### Export Only (from existing JSON)

```python
import json
from linkintel import exporters

# Load existing analysis result
with open("outputs/report.json", "r") as f:
    result = json.load(f)

# Export to PDF
exporters.export_to_pdf(result, "example.com", "report.pdf")

# Export to PPTX
exporters.export_to_pptx(result, "example.com", "report.pptx")
```

## PDF Report Sections

1. **Title Page** - Domain, date, executive metrics
2. **Executive Summary** - Key metrics dashboard
3. **Issues Overview** - Severity-coded issues
4. **Topical Clusters** - Authority analysis with hub pages
5. **Anchor Text Analysis** - Over-optimized, generic, and empty anchors
6. **Link Recommendations** - Top contextual linking opportunities
7. **Footer** - Auto-numbered pages with generation timestamp

## PPTX Presentation Slides

1. **Title Slide** - Blue gradient background with key metrics
2. **Executive Summary** - Metrics overview
3. **Issues & Opportunities** - Color-coded severity levels
4. **Section: Topical Clusters & Authority**
5. **Cluster Overview** - Hub pages and authority patterns
6. **Anchor Text Analysis** - Issues and recommendations
7. **Link Recommendations** - Top 5 opportunities with anchors
8. **Strategic Recommendations** - 6 actionable next steps

## Styling & Branding

### PDF
- Blue accent color (#3B82F6)
- Professional sans-serif typography
- Proper table formatting with alternating row colors
- Badge system for severity levels

### PPTX
- Consistent blue brand color (#3B82F6)
- Dark section title slides
- White content slides with blue headers
- Professional spacing and alignment
- Color-coded metrics and badges

## Troubleshooting

### "WeasyPrint not installed"
```bash
pip install WeasyPrint
# Note: May require additional system dependencies
# macOS: brew install python3 libffi libjpeg libpng
# Ubuntu: apt-get install python3-dev libffi-dev libjpeg-dev
# Windows: Use pre-built wheels or WSL
```

### "python-pptx not installed"
```bash
pip install python-pptx
```

### PDF appears blank or corrupted
- Ensure WeasyPrint is properly installed with all dependencies
- Try with a smaller dataset first
- Check file permissions in output directory

### PPTX text appears cut off
- This is normal behavior; adjust font sizes in the source code if needed
- PPTX has built-in text wrapping that adapts to slide dimensions

## Performance Notes

- **PDF Generation:** ~2-5 seconds for typical sites (100-300 pages)
- **PPTX Generation:** ~1-2 seconds for typical sites
- **HTML Generation:** <1 second

Large sites (1000+ pages) may take longer; no data limit in the exporters.

## Customization

To modify styling, edit `exporters.py`:

- **PDF Styles:** Modify CSS in `_generate_pdf_html()` function
- **PPTX Styling:** Modify colors/fonts in the `export_to_pptx()` function

Example: Change PDF accent color from blue to green
```python
# In _generate_pdf_html(), change:
fill.fore_color.rgb = RGBColor(34, 197, 94)  # Green instead of blue
```

## Example Report Structure

### PDF (Single-file, print-ready)
```
Report Title
├── Executive Summary (metrics cards)
├── Issues Overview (severity badges)
├── Topical Clusters (table view)
├── Anchor Text Analysis (issues table)
├── Link Recommendations (opportunities)
└── Footer (page numbers)
```

### PPTX (Presentation, slideshow-ready)
```
Slide 1: Title Slide
Slide 2: Executive Summary
Slide 3: Issues & Opportunities
Slide 4: Section - Topical Clusters
Slide 5: Cluster Overview
Slide 6: Anchor Text Analysis
Slide 7: Link Recommendations
Slide 8: Strategic Recommendations
```

## Limitations

- PDF: Large datasets (10k+ links) may take longer to render
- PPTX: Limited to 256 colors in some older Office versions
- Both: Require valid analysis data (cannot export empty/null results)

## Future Enhancements

- [ ] Custom branding (logos, colors, fonts)
- [ ] Multi-language support
- [ ] Template system for different report types
- [ ] Excel export for raw data
- [ ] Interactive PDF (hyperlinks, bookmarks)
