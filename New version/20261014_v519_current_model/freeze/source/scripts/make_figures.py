from __future__ import annotations

import argparse
import csv
import html
import json
import statistics
from pathlib import Path

COLORS = ["#2E74B5", "#D97706", "#059669", "#7C3AED"]


def load_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def bar_chart(path, title, categories, series, *, percent=False, width=1100, height=600):
    margin = {"left": 90, "right": 30, "top": 90, "bottom": 145}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    values = [value for _, mapping in series for value in mapping.values()]
    maximum = max(values, default=1.0)
    y_max = 1.0 if percent or maximum <= 1.0 else maximum * 1.1
    group_w = plot_w / max(1, len(categories))
    bar_w = min(34, group_w * 0.72 / max(1, len(series)))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        f'<text x="{width/2}" y="38" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="24" font-weight="700" fill="#0B2545">{html.escape(title)}</text>',
    ]
    for tick in range(6):
        value = y_max * tick / 5
        y = margin["top"] + plot_h - plot_h * tick / 5
        label = f"{value * 100:.0f}%" if percent else f"{value:.2f}"
        parts += [
            f'<line x1="{margin["left"]}" y1="{y:.1f}" x2="{margin["left"] + plot_w}" y2="{y:.1f}" stroke="#E2E8F0"/>',
            f'<text x="{margin["left"] - 12}" y="{y + 5:.1f}" text-anchor="end" font-family="Arial" font-size="13" fill="#475569">{label}</text>',
        ]
    for category_index, category in enumerate(categories):
        center = margin["left"] + group_w * (category_index + 0.5)
        total_bar_w = bar_w * len(series)
        for series_index, (name, mapping) in enumerate(series):
            value = float(mapping.get(category, 0.0))
            x = center - total_bar_w / 2 + series_index * bar_w
            height_px = plot_h * value / max(y_max, 1e-12)
            y = margin["top"] + plot_h - height_px
            color = COLORS[series_index % len(COLORS)]
            parts.append(f'<rect x="{x + 2:.1f}" y="{y:.1f}" width="{max(2, bar_w - 4):.1f}" height="{height_px:.1f}" rx="2" fill="{color}"/>')
        label_x = center
        label_y = margin["top"] + plot_h + 18
        parts.append(f'<text x="{label_x:.1f}" y="{label_y:.1f}" transform="rotate(35 {label_x:.1f} {label_y:.1f})" text-anchor="start" font-family="Microsoft YaHei, sans-serif" font-size="12" fill="#334155">{html.escape(category)}</text>')
    legend_x = margin["left"]
    for index, (name, _) in enumerate(series):
        x = legend_x + index * 200
        parts.append(f'<rect x="{x}" y="58" width="16" height="16" rx="2" fill="{COLORS[index % len(COLORS)]}"/>')
        parts.append(f'<text x="{x + 23}" y="71" font-family="Microsoft YaHei, sans-serif" font-size="13" fill="#334155">{html.escape(name)}</text>')
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def latency_chart(path, title, rows, *, width=1100, height=600):
    """Create a categorical line plot with min--max whiskers for isolated latency."""
    margin = {"left": 96, "right": 36, "top": 92, "bottom": 86}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    maximum = max(float(row["max_seconds"]) for row in rows) * 1.10
    y_max = max(1.0, maximum)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        f'<text x="{width/2}" y="38" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="24" font-weight="700" fill="#0B2545">{html.escape(title)}</text>',
        '<text x="96" y="70" font-family="Microsoft YaHei, sans-serif" font-size="13" fill="#475569">误差线：五次重复的最小—最大值；点：中位数</text>',
    ]
    for tick in range(6):
        value = y_max * tick / 5
        y = margin["top"] + plot_h - plot_h * tick / 5
        parts += [
            f'<line x1="{margin["left"]}" y1="{y:.1f}" x2="{margin["left"] + plot_w}" y2="{y:.1f}" stroke="#E2E8F0"/>',
            f'<text x="{margin["left"] - 12}" y="{y + 5:.1f}" text-anchor="end" font-family="Arial" font-size="13" fill="#475569">{value:.0f}</text>',
        ]
    parts.append(f'<text x="24" y="{margin["top"] + plot_h / 2:.1f}" transform="rotate(-90 24 {margin["top"] + plot_h / 2:.1f})" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="14" fill="#334155">定位时间（秒）</text>')
    points = []
    for index, row in enumerate(rows):
        x = margin["left"] + plot_w * (index + 0.5) / len(rows)
        median = float(row["median_seconds"])
        low = float(row["min_seconds"])
        high = float(row["max_seconds"])
        y = margin["top"] + plot_h * (1 - median / y_max)
        low_y = margin["top"] + plot_h * (1 - low / y_max)
        high_y = margin["top"] + plot_h * (1 - high / y_max)
        parts += [
            f'<line x1="{x:.1f}" y1="{low_y:.1f}" x2="{x:.1f}" y2="{high_y:.1f}" stroke="#94A3B8" stroke-width="2"/>',
            f'<line x1="{x - 6:.1f}" y1="{low_y:.1f}" x2="{x + 6:.1f}" y2="{low_y:.1f}" stroke="#94A3B8" stroke-width="2"/>',
            f'<line x1="{x - 6:.1f}" y1="{high_y:.1f}" x2="{x + 6:.1f}" y2="{high_y:.1f}" stroke="#94A3B8" stroke-width="2"/>',
            f'<text x="{x:.1f}" y="{margin["top"] + plot_h + 30:.1f}" text-anchor="middle" font-family="Arial" font-size="14" fill="#334155">{html.escape(str(row["target_formula_count"]))}</text>',
            f'<text x="{x:.1f}" y="{y - 12:.1f}" text-anchor="middle" font-family="Arial" font-size="13" fill="#0B2545">{median:.1f}s</text>',
        ]
        points.append((x, y))
    if points:
        parts.append('<polyline points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in points) + '" fill="none" stroke="#2E74B5" stroke-width="3"/>')
        parts.extend(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#2E74B5"/>' for x, y in points)
    parts.append(f'<text x="{margin["left"] + plot_w / 2:.1f}" y="{height - 18}" text-anchor="middle" font-family="Microsoft YaHei, sans-serif" font-size="14" fill="#334155">工作簿中的公式数量</text>')
    parts.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def build_latency_artifacts(results, output):
    source = results / "performance_v3_latency.csv"
    if not source.exists():
        return
    grouped = {}
    for row in load_csv(source):
        if row.get("measurement_mode") != "latency" or row.get("worker_count") != "1":
            raise ValueError("Latency artifact requires isolated --mode latency --workers 1 measurements")
        grouped.setdefault(int(row["target_formula_count"]), []).append(float(row["localization_seconds"]))
    rows = [{
        "target_formula_count": size,
        "min_seconds": min(values),
        "median_seconds": statistics.median(values),
        "max_seconds": max(values),
        "samples": len(values),
    } for size, values in sorted(grouped.items())]
    latency_chart(output / "performance_latency.svg", "FormulaGuard v3：单工作簿定位延迟", rows)
    table_path = output / "performance_latency_table.md"
    lines = [
        "# 表6-6：FormulaGuard v3 单工作簿性能",
        "",
        "条件：隔离单进程、每个规模重复5次、candidate_limit=15。时间单位为秒。",
        "",
        "| 公式数 | 重复数 | 定位最小值 | 定位中位数 | 定位最大值 |",
        "|---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {row['target_formula_count']} | {row['samples']} | {row['min_seconds']:.2f} | {row['median_seconds']:.2f} | {row['max_seconds']:.2f} |"
        for row in rows
    )
    lines += [
        "",
        "注：该表度量单份工作簿的隔离诊断延迟，不包含多进程批量吞吐；因此可用于描述当前原型的离线审计成本，不应被解释为实时插件性能。",
    ]
    table_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Generate paper-ready SVG figures from measured CSV files")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.results / "figures"
    summary = load_csv(args.results / "summary.csv")
    comparison = json.loads((args.results / "paired_comparison.json").read_text(encoding="utf-8"))
    strongest = comparison["strongest_no_oracle_baseline"]
    preferred_order = [
        "random", "excel_like", "pattern", "graph", "behavior",
        "excelint_like", "warder_like", "formulaguard", "formulaguard_v3", "sfl_oracle",
    ]
    summary_map = {row["method"]: row for row in summary}
    primary_method = "formulaguard_v3" if "formulaguard_v3" in summary_map else "formulaguard"
    methods = [method for method in preferred_order if method in summary_map]
    bar_chart(output / "main_mrr.svg", "主实验：MRR", methods, [("MRR", {method: float(summary_map[method]["mrr"]) for method in methods})], percent=False)
    bar_chart(output / "main_top5.svg", "主实验：Top-5 命中率", methods, [("Top-5", {method: float(summary_map[method]["top5"]) for method in methods})], percent=True)

    for filename, source_name, key_name, title in [
        ("by_depth_mrr.svg", "by_depth.csv", "depth_bin", "传播深度分层：MRR"),
        ("by_error_mrr.svg", "by_error.csv", "mutation_type", "错误类型分层：MRR"),
        ("by_topology_mrr.svg", "by_topology.csv", "topology_id", "Dependency topology: MRR"),
    ]:
        rows = load_csv(args.results / source_name)
        categories = sorted({row[key_name] for row in rows})
        fg = {row[key_name]: float(row["mrr"]) for row in rows if row["method"] == primary_method}
        baseline = {row[key_name]: float(row["mrr"]) for row in rows if row["method"] == strongest}
        bar_chart(output / filename, title, categories, [(primary_method, fg), (strongest, baseline)], percent=False)
    build_latency_artifacts(args.results, output)
    print(output)


if __name__ == "__main__":
    main()
