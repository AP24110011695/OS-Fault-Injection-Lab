import csv
import random
from pathlib import Path
from typing import Any

import matplotlib as mpl
import matplotlib.pyplot as plt

import config
from experiment.metrics import compute_aggregates

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# Chart groups: process_hang appears twice (one row per recovery strategy) and
# both rows keep the fault's color, per design.md.
GROUP_ORDER: list[str] = [
    "process_kill",
    "memory_pressure",
    "cpu_hog",
    "process_hang_resume",
    "process_hang_restart",
    "disk_full",
    "fd_exhaustion",
    "zombie_leak",
]

GROUP_LABELS: dict[str, str] = {
    "process_kill": "Process Kill",
    "memory_pressure": "Memory Pressure",
    "cpu_hog": "CPU Hog",
    "process_hang_resume": "Process Hang (resume)",
    "process_hang_restart": "Process Hang (restart)",
    "disk_full": "Disk Full",
    "fd_exhaustion": "FD Exhaustion",
    "zombie_leak": "Zombie Leak",
}

GROUP_COLORS: dict[str, str] = {
    "process_kill": "#4A7C8F",
    "memory_pressure": "#C47B5A",
    "cpu_hog": "#6B9080",
    "process_hang_resume": "#8B7BA5",
    "process_hang_restart": "#8B7BA5",
    "disk_full": "#B49A5A",
    "fd_exhaustion": "#B07A8C",
    "zombie_leak": "#7080A0",
}

RAMP_UP_NOTE: str = (
    "MTTD includes each fault's own ramp-up time (configured fill/leak/spawn speed) "
    "plus the debounce, so use the recovery-time chart to compare recovery cost."
)


def apply_chart_style() -> None:
    """Apply the project's visual style to all subsequent charts per design.md."""
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
        "font.sans-serif": ["DejaVu Sans", "Helvetica Neue", "Arial", "sans-serif"],
        "font.serif": ["DejaVu Serif", "Georgia", "serif"],
        "figure.figsize": (8, 5),
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
        "savefig.facecolor": "#FAFAF8",
    })


def group_of(trial_id: str) -> str:
    """Chart group for a trial id: everything before the numeric suffix
    (process_hang_resume_001 -> process_hang_resume)."""
    return trial_id.rsplit("_", 1)[0]


def write_results_csv(
    trial_metrics: list[dict[str, Any]],
    csv_path: Path | str | None = None,
) -> None:
    path: Path = Path(csv_path or config.RESULTS_CSV_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames: list[str] = ["trial_id", "fault_type", "mttd_sec", "mttr_sec", "success"]
    existing_rows: list[dict[str, Any]] = []
    if path.exists():
        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                new_ids = {m["trial_id"] for m in trial_metrics}
                existing_rows = [row for row in reader if row.get("trial_id") not in new_ids]
        except Exception:
            existing_rows = []

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in existing_rows:
            writer.writerow(r)
        for m in trial_metrics:
            writer.writerow({
                "trial_id": m["trial_id"],
                "fault_type": m["fault_type"],
                "mttd_sec": f"{m['mttd_sec']:.4f}" if m["mttd_sec"] is not None else "",
                "mttr_sec": f"{m['mttr_sec']:.4f}" if m["mttr_sec"] is not None else "",
                "success": m["success"],
            })


def read_results_csv(csv_path: Path | str | None = None) -> list[dict[str, Any]]:
    path: Path = Path(csv_path or config.RESULTS_CSV_PATH)
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "trial_id": r["trial_id"],
                "fault_type": r["fault_type"],
                "mttd_sec": float(r["mttd_sec"]) if r.get("mttd_sec") else None,
                "mttr_sec": float(r["mttr_sec"]) if r.get("mttr_sec") else None,
                "success": r.get("success", "").lower() in ("true", "1", "yes"),
            })
    return rows


def print_summary_table(fault_type: str, trial_metrics: list[dict[str, Any]]) -> None:
    aggr = compute_aggregates(trial_metrics)
    count: int = aggr["count"]

    print(f"\nResults: {fault_type} ({count} trials)")
    print("---")
    print(f"{'':16}{'Mean':>8} {'Median':>9} {'Min':>8} {'Max':>8}")
    print(
        f"  {'MTTD (sec)':<14} {aggr['mttd_mean']:8.3f} {aggr['mttd_median']:9.3f} "
        f"{aggr['mttd_min']:8.3f} {aggr['mttd_max']:8.3f}"
    )
    print(
        f"  {'MTTR (sec)':<14} {aggr['mttr_mean']:8.3f} {aggr['mttr_median']:9.3f} "
        f"{aggr['mttr_min']:8.3f} {aggr['mttr_max']:8.3f}"
    )
    print(f"  {'Success rate':<14} {aggr['success_rate']:7.1f}%")
    print(f"\nResults saved to: {config.RESULTS_CSV_PATH}")


def _recovery_time(row: dict[str, Any]) -> float | None:
    """Time from detection to recovery: what the recovery action itself costs."""
    if row["mttd_sec"] is None or row["mttr_sec"] is None:
        return None
    return row["mttr_sec"] - row["mttd_sec"]


def _grouped_metric(rows: list[dict[str, Any]], metric: str) -> dict[str, list[float]]:
    """Per-group trial values for 'mttd_sec', 'mttr_sec', or 'recovery'."""
    values: dict[str, list[float]] = {}
    for r in rows:
        value: float | None = _recovery_time(r) if metric == "recovery" else r[metric]
        if value is not None:
            values.setdefault(group_of(r["trial_id"]), []).append(value)
    return values


def _ordered_groups(values: dict[str, list[float]]) -> list[str]:
    return [g for g in GROUP_ORDER if g in values]


def _draw_group_bars(
    groups: list[str],
    means: list[float],
    trial_values: list[list[float]],
    xlabel: str,
    title: str,
    path: Path,
    note: str | None = None,
) -> Path:
    """Horizontal bars with individual trial dots and direct value labels,
    following design.md (one color per fault, direct labels, no legend)."""
    apply_chart_style()
    fig, ax = plt.subplots(figsize=(8, 5))
    y_positions = range(len(groups))

    ax.barh(y_positions, means, height=0.5, color=[GROUP_COLORS[g] for g in groups], zorder=2)

    rng = random.Random(42)
    for y, points in zip(y_positions, trial_values):
        jittered_y = [y + rng.uniform(-0.14, 0.14) for _ in points]
        ax.scatter(points, jittered_y, color="#2D2D2D", alpha=0.55, s=24, zorder=3, linewidths=0)

    all_points = [p for points in trial_values for p in points]
    x_max = max([max(means)] + all_points) if all_points else max(means)
    for y, mean_val, points in zip(y_positions, means, trial_values):
        label_x = max([mean_val] + points) + x_max * 0.02
        ax.text(label_x, y, f"{mean_val:.2f}s", va="center", ha="left", fontsize=10,
                fontfamily="sans-serif", color="#2D2D2D")

    ax.set_yticks(list(y_positions))
    ax.set_yticklabels([GROUP_LABELS[g] for g in groups], fontsize=10)
    ax.invert_yaxis()  # first group at the top
    ax.set_xlabel(xlabel, fontsize=11, labelpad=8)
    ax.set_ylabel("Fault type", fontsize=11, labelpad=8)
    ax.grid(True, axis="x")  # grid along the value axis (horizontal bars)
    ax.grid(False, axis="y")
    ax.set_xlim(0, x_max * 1.22)

    ax.set_title(title, fontfamily="serif", fontsize=13, fontweight="bold", pad=16, color="#2D2D2D")
    if note:
        fig.text(0.02, -0.04, note, fontsize=8, color="#6B6B6B", ha="left")

    fig.savefig(path)
    plt.close(fig)
    return path


def generate_mttd_chart(rows: list[dict[str, Any]], output_path: Path | str | None = None) -> Path:
    path: Path = Path(output_path or (config.RESULTS_DIR / "mttd_by_fault.png"))
    path.parent.mkdir(parents=True, exist_ok=True)

    values = _grouped_metric(rows, "mttd_sec")
    groups = _ordered_groups(values)
    means = [sum(values[g]) / len(values[g]) for g in groups]
    fastest = groups[means.index(min(means))]
    slowest = groups[means.index(max(means))]
    title = f"Mean Detection Time Spans {min(means):.2f}s ({GROUP_LABELS[fastest]}) to {max(means):.2f}s ({GROUP_LABELS[slowest]})"

    return _draw_group_bars(
        groups, means, [values[g] for g in groups],
        "Mean Time to Detect (seconds)", title, path, note=RAMP_UP_NOTE,
    )


def generate_mttr_chart(rows: list[dict[str, Any]], output_path: Path | str | None = None) -> Path:
    path: Path = Path(output_path or (config.RESULTS_DIR / "mttr_by_fault.png"))
    path.parent.mkdir(parents=True, exist_ok=True)

    values = _grouped_metric(rows, "mttr_sec")
    groups = _ordered_groups(values)
    means = [sum(values[g]) / len(values[g]) for g in groups]
    overall = sum(means) / len(means)
    title = f"Recovery Averages {overall:.2f}s Across {len(groups)} Fault Groups"

    return _draw_group_bars(
        groups, means, [values[g] for g in groups],
        "Mean Time to Recover (seconds)", title, path,
    )


def generate_recovery_time_chart(rows: list[dict[str, Any]], output_path: Path | str | None = None) -> Path:
    path: Path = Path(output_path or (config.RESULTS_DIR / "recovery_time_by_fault.png"))
    path.parent.mkdir(parents=True, exist_ok=True)

    values = _grouped_metric(rows, "recovery")
    groups = _ordered_groups(values)
    means = [sum(values[g]) / len(values[g]) for g in groups]
    overall = sum(means) / len(means)
    title = f"Recovery Cost Beyond Detection Averages {overall:.2f}s"

    return _draw_group_bars(
        groups, means, [values[g] for g in groups],
        "Recovery time after detection: MTTR - MTTD (seconds)", title, path,
    )


def generate_success_rate_chart(rows: list[dict[str, Any]], output_path: Path | str | None = None) -> Path:
    path: Path = Path(output_path or (config.RESULTS_DIR / "success_rate.png"))
    path.parent.mkdir(parents=True, exist_ok=True)

    rates: dict[str, float] = {}
    for g in {group_of(r["trial_id"]) for r in rows}:
        g_rows = [r for r in rows if group_of(r["trial_id"]) == g]
        rates[g] = sum(1 for r in g_rows if r["success"]) / len(g_rows) * 100.0
    groups = _ordered_groups(rates)

    total_trials = len(rows)
    overall = sum(1 for r in rows if r["success"]) / total_trials * 100.0
    title = f"Automated Recovery Succeeded in {overall:.1f}% of {total_trials} Trials"

    apply_chart_style()
    fig, ax = plt.subplots(figsize=(8, 5))
    y_positions = range(len(groups))
    bars = ax.barh(y_positions, [rates[g] for g in groups], height=0.5,
                   color=[GROUP_COLORS[g] for g in groups], zorder=2)

    for bar, g in zip(bars, groups):
        ax.text(bar.get_width() + 1.5, bar.get_y() + bar.get_height() / 2.0,
                f"{rates[g]:.1f}%", va="center", ha="left", fontsize=10,
                fontfamily="sans-serif", color="#2D2D2D")

    ax.set_yticks(list(y_positions))
    ax.set_yticklabels([GROUP_LABELS[g] for g in groups], fontsize=10)
    ax.invert_yaxis()  # first group at the top
    ax.set_xlabel("Recovery success rate (%)", fontsize=11, labelpad=8)
    ax.set_ylabel("Fault type", fontsize=11, labelpad=8)
    ax.grid(True, axis="x")
    ax.grid(False, axis="y")
    ax.set_xlim(0, 115)

    ax.set_title(title, fontfamily="serif", fontsize=13, fontweight="bold", pad=16, color="#2D2D2D")
    fig.savefig(path)
    plt.close(fig)
    return path


def generate_all_charts(csv_path: Path | str | None = None) -> list[Path]:
    rows = read_results_csv(csv_path)
    if not rows:
        print(f"[warning] No results found in {csv_path or config.RESULTS_CSV_PATH}")
        return []

    charts = [
        generate_mttd_chart(rows),
        generate_mttr_chart(rows),
        generate_recovery_time_chart(rows),
        generate_success_rate_chart(rows),
    ]

    print("\nCharts saved to:")
    for c in charts:
        print(f"  {c}")
    return charts


def print_comparison_summary(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No results available to summarize.")
        return

    groups = _ordered_groups(_grouped_metric(rows, "mttd_sec"))
    total_trials = len(rows)
    overall_success = sum(1 for r in rows if r["success"]) / total_trials * 100.0

    print("\nComparison Summary")
    print(f"--- ({total_trials} trials across {len(groups)} fault groups) ---\n")
    print(f"  {'Fault group':<24}{'MTTD mean':>10} {'MTTR mean':>10} {'Recovery':>10} {'Success':>9}")
    for g in groups:
        g_rows = [r for r in rows if group_of(r["trial_id"]) == g]
        aggr = compute_aggregates(g_rows)
        recovery_cost = aggr["mttr_mean"] - aggr["mttd_mean"]
        print(
            f"  {GROUP_LABELS[g]:<24} {aggr['mttd_mean']:>9.3f} {aggr['mttr_mean']:>9.3f} "
            f"{recovery_cost:>9.3f} {aggr['success_rate']:>8.1f}%"
        )

    print(f"\n  Overall success rate: {overall_success:.1f}%")
    print(f"  Note: {RAMP_UP_NOTE}")
    print("---")


if __name__ == "__main__":
    rows = read_results_csv()
    if not rows:
        print("No results found in results/results.csv. Run experiments first.")
    else:
        generate_all_charts()
        print_comparison_summary(rows)
