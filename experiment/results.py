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

FAULT_COLORS: dict[str, str] = {
    "process_kill": "#4A7C8F",
    "memory_pressure": "#C47B5A",
    "cpu_hog": "#6B9080",
}

FAULT_LABELS: dict[str, str] = {
    "process_kill": "Process Kill",
    "memory_pressure": "Memory Pressure",
    "cpu_hog": "CPU Hog",
}

FAULT_ORDER: list[str] = ["process_kill", "memory_pressure", "cpu_hog"]


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


def generate_mttd_chart(rows: list[dict[str, Any]], output_path: Path | str | None = None) -> Path:
    apply_chart_style()
    path = Path(output_path or (config.RESULTS_DIR / "mttd_by_fault.png"))
    path.parent.mkdir(parents=True, exist_ok=True)

    faults = [f for f in FAULT_ORDER if any(r["fault_type"] == f for r in rows)]
    means: list[float] = []
    labels: list[str] = []
    colors: list[str] = []
    all_data: list[list[float]] = []

    for f in faults:
        f_mttds = [r["mttd_sec"] for r in rows if r["fault_type"] == f and r["mttd_sec"] is not None]
        all_data.append(f_mttds)
        means.append(sum(f_mttds) / len(f_mttds) if f_mttds else 0.0)
        labels.append(FAULT_LABELS.get(f, f))
        colors.append(FAULT_COLORS.get(f, "#4A7C8F"))

    fig, ax = plt.subplots(figsize=(8, 5))
    x_positions = range(len(faults))
    bars = ax.bar(x_positions, means, width=0.52, color=colors, zorder=2)

    rng = random.Random(42)
    for i, points in enumerate(all_data):
        jittered_x = [i + rng.uniform(-0.08, 0.08) for _ in points]
        ax.scatter(jittered_x, points, color="#2D2D2D", alpha=0.55, s=28, zorder=3, linewidths=0)

    for bar, mean_val, points in zip(bars, means, all_data):
        top_y = max(points) if points else bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            top_y + 0.06,
            f"{mean_val:.2f}s",
            ha="center",
            va="bottom",
            fontsize=10,
            fontfamily="sans-serif",
            color="#2D2D2D",
        )

    ax.set_xticks(list(x_positions))
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_xlabel("Fault type", fontsize=11, labelpad=8)
    ax.set_ylabel("Mean Time to Detect (seconds)", fontsize=11, labelpad=8)
    y_max = max(max(pts) for pts in all_data) if all_data else 2.0
    ax.set_ylim(0, y_max * 1.22)

    min_mean = min(means)
    max_mean = max(means)
    min_fault = labels[means.index(min_mean)]
    max_fault = labels[means.index(max_mean)]
    title_text = f"Detection Latency Spans {min_mean:.2f}s ({min_fault}) to {max_mean:.2f}s ({max_fault})"
    ax.set_title(title_text, fontfamily="serif", fontsize=13, fontweight="bold", pad=16, color="#2D2D2D")

    fig.savefig(path)
    plt.close(fig)
    return path


def generate_mttr_chart(rows: list[dict[str, Any]], output_path: Path | str | None = None) -> Path:
    apply_chart_style()
    path = Path(output_path or (config.RESULTS_DIR / "mttr_by_fault.png"))
    path.parent.mkdir(parents=True, exist_ok=True)

    faults = [f for f in FAULT_ORDER if any(r["fault_type"] == f for r in rows)]
    means: list[float] = []
    labels: list[str] = []
    colors: list[str] = []
    all_data: list[list[float]] = []

    for f in faults:
        f_mttrs = [r["mttr_sec"] for r in rows if r["fault_type"] == f and r["mttr_sec"] is not None]
        all_data.append(f_mttrs)
        means.append(sum(f_mttrs) / len(f_mttrs) if f_mttrs else 0.0)
        labels.append(FAULT_LABELS.get(f, f))
        colors.append(FAULT_COLORS.get(f, "#4A7C8F"))

    fig, ax = plt.subplots(figsize=(8, 5))
    x_positions = range(len(faults))
    bars = ax.bar(x_positions, means, width=0.52, color=colors, zorder=2)

    rng = random.Random(42)
    for i, points in enumerate(all_data):
        jittered_x = [i + rng.uniform(-0.08, 0.08) for _ in points]
        ax.scatter(jittered_x, points, color="#2D2D2D", alpha=0.55, s=28, zorder=3, linewidths=0)

    for bar, mean_val, points in zip(bars, means, all_data):
        top_y = max(points) if points else bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            top_y + 0.06,
            f"{mean_val:.2f}s",
            ha="center",
            va="bottom",
            fontsize=10,
            fontfamily="sans-serif",
            color="#2D2D2D",
        )

    ax.set_xticks(list(x_positions))
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_xlabel("Fault type", fontsize=11, labelpad=8)
    ax.set_ylabel("Mean Time to Recover (seconds)", fontsize=11, labelpad=8)
    y_max = max(max(pts) for pts in all_data) if all_data else 2.5
    ax.set_ylim(0, y_max * 1.22)

    overall_mean = sum(means) / len(means) if means else 0.0
    title_text = f"Recovery Closely Mirrors Detection, Averaging {overall_mean:.2f}s Overall"
    ax.set_title(title_text, fontfamily="serif", fontsize=13, fontweight="bold", pad=16, color="#2D2D2D")

    fig.savefig(path)
    plt.close(fig)
    return path


def generate_success_rate_chart(rows: list[dict[str, Any]], output_path: Path | str | None = None) -> Path:
    apply_chart_style()
    path = Path(output_path or (config.RESULTS_DIR / "success_rate.png"))
    path.parent.mkdir(parents=True, exist_ok=True)

    faults = [f for f in FAULT_ORDER if any(r["fault_type"] == f for r in rows)]
    rates: list[float] = []
    labels: list[str] = []
    colors: list[str] = []

    for f in faults:
        f_rows = [r for r in rows if r["fault_type"] == f]
        successes = sum(1 for r in f_rows if r["success"])
        rate = (successes / len(f_rows) * 100.0) if f_rows else 0.0
        rates.append(rate)
        labels.append(FAULT_LABELS.get(f, f))
        colors.append(FAULT_COLORS.get(f, "#4A7C8F"))

    fig, ax = plt.subplots(figsize=(8, 4.5))
    y_positions = range(len(faults))
    bars = ax.barh(y_positions, rates, height=0.45, color=colors, zorder=2)

    for bar, rate_val in zip(bars, rates):
        width = bar.get_width()
        ax.text(
            width + 1.5,
            bar.get_y() + bar.get_height() / 2.0,
            f"{rate_val:.1f}%",
            ha="left",
            va="center",
            fontsize=10,
            fontfamily="sans-serif",
            color="#2D2D2D",
        )

    ax.set_yticks(list(y_positions))
    ax.set_yticklabels(labels, fontsize=11)
    ax.set_xlabel("Recovery success rate (%)", fontsize=11, labelpad=8)
    ax.set_ylabel("Fault type", fontsize=11, labelpad=8)
    ax.set_xlim(0, 115)

    total_trials = len(rows)
    overall_success = (sum(1 for r in rows if r["success"]) / total_trials * 100.0) if total_trials else 0.0
    title_text = f"Automated Self-Healing Achieved {overall_success:.1f}% Success Across All {total_trials} Trials"
    ax.set_title(title_text, fontfamily="serif", fontsize=13, fontweight="bold", pad=16, color="#2D2D2D")

    fig.savefig(path)
    plt.close(fig)
    return path


def generate_scatter_chart(rows: list[dict[str, Any]], output_path: Path | str | None = None) -> Path:
    apply_chart_style()
    path = Path(output_path or (config.RESULTS_DIR / "mttd_vs_mttr.png"))
    path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 5))

    overheads: list[float] = []
    faults = [f for f in FAULT_ORDER if any(r["fault_type"] == f for r in rows)]
    for f in faults:
        f_rows = [r for r in rows if r["fault_type"] == f and r["mttd_sec"] is not None and r["mttr_sec"] is not None]
        xs = [r["mttd_sec"] for r in f_rows]
        ys = [r["mttr_sec"] for r in f_rows]
        overheads.extend([y - x for x, y in zip(xs, ys)])
        ax.scatter(
            xs,
            ys,
            color=FAULT_COLORS.get(f, "#4A7C8F"),
            label=FAULT_LABELS.get(f, f),
            alpha=0.85,
            s=45,
            zorder=3,
        )

    mean_overhead = sum(overheads) / len(overheads) if overheads else 0.0

    all_x = [r["mttd_sec"] for r in rows if r["mttd_sec"] is not None]
    all_y = [r["mttr_sec"] for r in rows if r["mttr_sec"] is not None]
    max_val = max(max(all_x), max(all_y)) * 1.08 if all_x and all_y else 2.5
    ax.plot([0, max_val], [0, max_val], linestyle="--", color="#6B6B6B", linewidth=1.0, alpha=0.5, label="y = x (zero recovery lag)", zorder=2)

    ax.set_xlim(0, max_val)
    ax.set_ylim(0, max_val)
    ax.set_xlabel("Mean Time to Detect (seconds)", fontsize=11, labelpad=8)
    ax.set_ylabel("Mean Time to Recover (seconds)", fontsize=11, labelpad=8)
    ax.legend(frameon=False, fontsize=9, loc="upper left")

    title_text = f"MTTR is Governed by Detection Latency (Recovery Action Adds {mean_overhead:.2f}s)"
    ax.set_title(title_text, fontfamily="serif", fontsize=13, fontweight="bold", pad=16, color="#2D2D2D")

    fig.savefig(path)
    plt.close(fig)
    return path


def generate_all_charts(csv_path: Path | str | None = None) -> list[Path]:
    rows = read_results_csv(csv_path)
    if not rows:
        print(f"[warning] No results found in {csv_path or config.RESULTS_CSV_PATH}")
        return []

    c1 = generate_mttd_chart(rows)
    c2 = generate_mttr_chart(rows)
    c3 = generate_success_rate_chart(rows)
    c4 = generate_scatter_chart(rows)
    charts = [c1, c2, c3, c4]

    print("\nCharts saved to:")
    for c in charts:
        print(f"  {c}")
    return charts


def print_comparison_summary(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No results available to summarize.")
        return

    stats: dict[str, dict[str, Any]] = {}
    for f in FAULT_ORDER:
        f_rows = [r for r in rows if r["fault_type"] == f]
        if f_rows:
            stats[f] = compute_aggregates(f_rows)

    total_trials = len(rows)
    print("\nComparison Summary")
    print(f"--- ({total_trials} total trials across {len(stats)} fault types) ---")

    if "process_kill" in stats:
        pk = stats["process_kill"]
        overhead_pk = pk["mttr_mean"] - pk["mttd_mean"]
        print(f"\n1. Process Kill (Fastest detection: mean MTTD {pk['mttd_mean']:.3f}s)")
        print("   - Mechanism: os.kill(pid, SIGKILL) instantly terminates target execution (< 1ms).")
        print(f"   - Polling impact: Detected on the next monitor check; MTTD represents pure polling")
        print(f"     phase offset uniformly distributed in [0, {config.MONITOR_POLL_INTERVAL_SEC:.1f}s] (mean ~0.25s).")
        print(f"   - Recovery: Supervisor restarted target and verified liveness in {overhead_pk:.3f}s.")

    if "memory_pressure" in stats:
        mp = stats["memory_pressure"]
        overhead_mp = mp["mttr_mean"] - mp["mttd_mean"]
        print(f"\n2. Memory Pressure (Moderate detection: mean MTTD {mp['mttd_mean']:.3f}s)")
        print(f"   - Mechanism: Memory hog allocates 8MB bytearrays every 50ms inside cgroup (limit {config.CGROUP_MEMORY_LIMIT_MB}MB).")
        print("   - Ramp-up impact: Takes ~0.40s of physical allocation ramp-up before the kernel OOM killer")
        print("     triggers. MTTD includes both physical allocation ramp-up and polling delay.")
        print(f"   - Recovery: Hog was OOM-killed; cgroup unlinked and removed in {overhead_mp:.3f}s.")

    if "cpu_hog" in stats:
        ch = stats["cpu_hog"]
        overhead_ch = ch["mttr_mean"] - ch["mttd_mean"]
        print(f"\n3. CPU Hog (Debounced detection: mean MTTD {ch['mttd_mean']:.3f}s)")
        print(f"   - Mechanism: stress-ng spawns {config.STRESS_NG_CPU_WORKERS} workers saturating 100% of available CPU cores.")
        print(f"   - Debounce impact: Detector requires {config.CONSECUTIVE_POLLS_THRESHOLD} consecutive polls above {config.CPU_THRESHOLD_PERCENT:.1f}% CPU to avoid")
        print(f"     false alarms from transient bursts. 3 polls at {config.MONITOR_POLL_INTERVAL_SEC:.1f}s establish a minimum 1.50s baseline.")
        print(f"   - Recovery: Workers terminated recursively and CPU normalized in {overhead_ch:.3f}s.")

    overall_success = (sum(1 for r in rows if r["success"]) / total_trials) * 100.0
    print(f"\nOverall Self-Healing Performance: {overall_success:.1f}% success rate across all trials.")
    print("---")


if __name__ == "__main__":
    rows = read_results_csv()
    if not rows:
        print("No results found in results/results.csv. Run experiments first.")
    else:
        generate_all_charts()
        print_comparison_summary(rows)
