from __future__ import annotations

import argparse
import csv
import html
import json
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
    print(output)


if __name__ == "__main__":
    main()
