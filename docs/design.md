# Design System — OS Fault Injection Lab

This document defines the visual language for everything the user sees:
matplotlib charts, CLI output, the README, and the optional HTML results report.

The overarching principle: **look like a thoughtful human made it, not a template generator.**
Restrained, clear, quiet confidence. A student should be proud to show this in a viva.

---

## Color Palette

A small, muted palette. No neon, no gradients, no decorative color.

| Role              | Color       | Hex       | Usage |
|-------------------|-------------|-----------|-------|
| Background        | Off-white   | `#FAFAF8` | Chart backgrounds, page background |
| Text              | Dark grey   | `#2D2D2D` | All body text, axis labels, titles |
| Light text        | Medium grey | `#6B6B6B` | Secondary labels, annotations |
| Gridlines         | Pale grey   | `#E0E0E0` | Chart gridlines only |
| Accent 1 (primary)| Muted blue  | `#4A7C8F` | Process kill fault, primary action |
| Accent 2          | Warm clay   | `#C47B5A` | Memory pressure fault |
| Accent 3          | Sage green  | `#6B9080` | CPU hog fault |
| Accent 4          | Muted violet| `#8B7BA5` | Process hang fault |
| Accent 5          | Muted ochre | `#B49A5A` | Disk full fault |
| Accent 6          | Dusty rose  | `#B07A8C` | FD exhaustion fault |
| Accent 7          | Slate indigo| `#7080A0` | Zombie leak fault |
| Error/failure     | Soft red    | `#B85450` | Failed trials, error states |
| Success           | Muted teal  | `#5A8F7B` | Successful recovery |

**Rules:**
- Each fault type always uses its assigned color. No exceptions.
- Charts comparing all seven faults use one color per fault (seven colors).
- Every other chart never uses more than 3 colors.
- Background is always `#FAFAF8`, never pure white (`#FFFFFF`).

---

## Typography

### In Charts (matplotlib)

| Element       | Font                    | Size | Weight   |
|---------------|-------------------------|------|----------|
| Chart title   | `Georgia` or `serif`    | 14   | Bold     |
| Axis labels   | `Helvetica Neue`, `Arial`, or `sans-serif` | 11 | Normal |
| Tick labels   | `Helvetica Neue`, `Arial`, or `sans-serif` | 10 | Normal |
| Annotations   | `Helvetica Neue`, `Arial`, or `sans-serif` | 9  | Normal |
| Data labels   | `SF Mono`, `Consolas`, or `monospace`       | 9  | Normal |

Fall back gracefully: matplotlib will use the generic family (`serif`, `sans-serif`, `monospace`)
if specific fonts are not installed in the Docker container. This is fine.

### In CLI Output

- Use plain ASCII. No emoji, no Unicode box-drawing characters.
- Align columns with spaces, not tabs.
- Use `---` separators between sections.
- Keep output width under 80 characters where practical.

### In Documentation (README, docs/)

- Markdown only. No custom HTML in docs.
- Headings: `#` for title, `##` for sections, `###` for subsections. No deeper nesting.
- Code blocks with language tags (````python`, ````bash`).
- Tables for structured data.

---

## Chart Design Rules

### General

1. **Title states the finding, not the chart type.**
   - Good: "Process kill faults are detected within 1.5 seconds on average"
   - Bad: "MTTD Bar Chart"

2. **Labeled axes with units.**
   - X-axis: `"Trial number"` or `"Fault type"`
   - Y-axis: `"Time (seconds)"` or `"Success rate (%)"`

3. **Direct labels over legends.**
   - If a chart has ≤3 series, label each bar/line directly.
   - With seven faults, use horizontal bars and put the fault name at each bar as the direct label.
   - Use a legend only when direct labels would overlap or clutter.

4. **Light gridlines.** Horizontal only (y-axis). Color: `#E0E0E0`. No vertical gridlines.

5. **No chart border (spines).** Remove top and right spines. Keep bottom and left.

6. **Consistent figure size.** Default: `(8, 5)` inches. Adjust only if data demands it.

7. **High DPI for export.** Save PNGs at `dpi=150`. Good for screens, reasonable file size.

8. **No 3D charts, no pie charts, no stacked bars.** Flat, honest representations only.

### Specific Charts to Produce

#### Chart 1: MTTD by Fault Type (grouped bar or box plot)

- X-axis: fault type (all seven).
- Y-axis: MTTD in seconds.
- Show individual trial dots overlaid on the bar/box for transparency.
- Title: a sentence summarizing the key insight.
- With seven categories, prefer horizontal bars (fault names on the y-axis) so labels stay readable.

#### Chart 2: MTTR by Fault Type (same format as Chart 1)

#### Chart 3: Success Rate by Fault Type (horizontal bar)

- X-axis: success rate (0%–100%).
- Y-axis: fault type.
- Direct label on each bar showing the percentage.
- This layout scales well to seven faults; keep it for the all-fault comparison.

#### Chart 4: Recovery Cost After Detection (MTTR − MTTD, horizontal bar)

- Y-axis: fault type (all eight groups; process_hang appears once per strategy in its own color).
- X-axis: recovery time in seconds (MTTR minus MTTD, per trial dots + mean bar).
- This isolates what the recovery action itself costs, independent of each fault's detection ramp-up.
- Replaces the earlier MTTD-vs-MTTR scatter (the horizontal-bar form carries the same information more readably for 7 faults).

### matplotlib Setup Code Pattern

```python
import matplotlib.pyplot as plt
import matplotlib as mpl

def apply_chart_style() -> None:
    """Apply the project's visual style to all subsequent charts."""
    mpl.rcParams.update({
        "figure.facecolor": "#FAFAF8",
        "axes.facecolor": "#FAFAF8",
        "axes.edgecolor": "#2D2D2D",
        "axes.labelcolor": "#2D2D2D",
        "text.color": "#2D2D2D",
        "xtick.color": "#2D2D2D",
        "ytick.color": "#2D2D2D",
        "grid.color": "#E0E0E0",
        "grid.linewidth": 0.5,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Arial", "sans-serif"],
        "figure.figsize": (8, 5),
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
        "savefig.facecolor": "#FAFAF8",
    })

# Fault type colors — use these consistently everywhere
FAULT_COLORS = {
    "process_kill": "#4A7C8F",
    "memory_pressure": "#C47B5A",
    "cpu_hog": "#6B9080",
    "process_hang": "#8B7BA5",
    "disk_full": "#B49A5A",
    "fd_exhaustion": "#B07A8C",
    "zombie_leak": "#7080A0",
}
```

---

## CLI Output Style

### Progress During Experiment

```
OS Fault Injection Lab
---

Running: process_kill | Trial 3 of 15
  Injected    0.000s
  Detected    0.823s  (MTTD: 0.823s)
  Recovered   1.241s  (MTTR: 1.241s)
  Status: OK

---
```

### Summary After All Trials

```
Results: process_kill (15 trials)
---
                  Mean     Median   Min      Max
  MTTD (sec)     0.847    0.823    0.501    1.203
  MTTR (sec)     1.289    1.241    0.892    1.744
  Success rate   93.3%

Results saved to: results/results.csv
Charts saved to:  results/mttd_by_fault.png
                  results/mttr_by_fault.png
                  results/success_rate.png
```

### Error Messages

```
ERROR: Not running inside Docker. Fault injection is disabled for safety.
       Run this project with: docker compose up --build
```

Plain, direct, helpful. No stack traces unless debugging.

---

## Optional HTML Report

If built (low priority, Phase 10 stretch goal):

- Single static HTML file, no JavaScript framework.
- Inline CSS only.
- Background: `#FAFAF8`.
- Font: system font stack (`-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`).
- Embed chart PNGs as `<img>` tags.
- Simple table for results data.
- No animations, no interactivity, no external dependencies.
- Must render correctly when opened as a local file (`file://`).

---

## Anti-Patterns (Do NOT Do These)

- No emoji in output or charts.
- No gradient fills on bars or backgrounds.
- No drop shadows.
- No rounded-corner "card" layouts.
- No "dashboard" aesthetic.
- No decorative icons.
- No color for decoration — only for information.
- No more than 3 colors in any single chart — except charts comparing all faults, which use one color per fault.
- No legends when direct labels suffice.
- No titles that describe the chart type instead of the finding.
