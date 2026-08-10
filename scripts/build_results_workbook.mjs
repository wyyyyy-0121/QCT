import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function argsOf(argv) {
  const args = {
    results: path.join(ROOT, "results", "quick"),
    validation: path.join(ROOT, "data", "propagationbench_quick", "validation"),
    output: path.join(ROOT, "outputs", "FormulaGuard_experiment_results.xlsx"),
  };
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i] === "--results") args.results = path.resolve(argv[++i]);
    else if (argv[i] === "--validation") args.validation = path.resolve(argv[++i]);
    else if (argv[i] === "--output") args.output = path.resolve(argv[++i]);
    else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  return args;
}

function rowCount(csvText) {
  return csvText.trim().split(/\r?\n/).length;
}

function parseCsv(csvText) {
  const rows = [];
  let row = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < csvText.length; index += 1) {
    const char = csvText[index];
    if (quoted) {
      if (char === '"' && csvText[index + 1] === '"') {
        value += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        value += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(value);
      value = "";
    } else if (char === "\n") {
      row.push(value.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      value = "";
    } else {
      value += char;
    }
  }
  if (value || row.length) {
    row.push(value.replace(/\r$/, ""));
    rows.push(row);
  }
  return rows;
}

function columnName(oneBasedIndex) {
  let value = oneBasedIndex;
  let result = "";
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function literalizeCsvColumn(csvText, headerName) {
  const rows = parseCsv(csvText);
  if (!rows.length) return csvText;
  const columnIndex = rows[0].indexOf(headerName);
  if (columnIndex < 0) return csvText;
  for (const row of rows.slice(1)) {
    const value = row[columnIndex] ?? "";
    if (value.startsWith("=")) row[columnIndex] = `'${value}`;
  }
  return rows.map(row => row.map(csvCell).join(",")).join("\n") + "\n";
}

function restoreLiteralColumn(workbook, sheetName, csvText, headerName) {
  const rows = parseCsv(csvText);
  if (rows.length < 2) return;
  const columnIndex = rows[0].indexOf(headerName);
  if (columnIndex < 0) return;
  const column = columnName(columnIndex + 1);
  const values = rows.slice(1).map(row => {
    const value = row[columnIndex] ?? "";
    return [value.startsWith("=") ? `'${value}` : value];
  });
  workbook.worksheets.getItem(sheetName).getRange(`${column}2:${column}${values.length + 1}`).values = values;
}

function styleTabularSheet(sheet, lastColumn, rows, widths = {}) {
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(1);
  const used = sheet.getRange(`A1:${lastColumn}${Math.max(1, rows)}`);
  used.format.font = { name: "Microsoft YaHei", size: 9 };
  used.format.verticalAlignment = "center";
  used.format.borders = {
    insideHorizontal: { style: "thin", color: "#E2E8F0" },
    bottom: { style: "thin", color: "#CBD5E1" },
  };
  sheet.getRange(`A1:${lastColumn}1`).format = {
    fill: "#0B2545",
    font: { name: "Microsoft YaHei", size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#0B2545" },
  };
  for (const [column, width] of Object.entries(widths)) {
    sheet.getRange(`${column}:${column}`).format.columnWidth = width;
  }
}

async function main() {
  const args = argsOf(process.argv);
  const summaryText = await fs.readFile(path.join(args.results, "summary.csv"), "utf8");
  const depthText = await fs.readFile(path.join(args.results, "by_depth.csv"), "utf8");
  const errorText = await fs.readFile(path.join(args.results, "by_error.csv"), "utf8");
  const familyText = await fs.readFile(path.join(args.results, "by_family.csv"), "utf8");
  const topologyText = await fs.readFile(path.join(args.results, "by_topology.csv"), "utf8").catch(error => {
    if (error?.code === "ENOENT") return "topology_id,method,instances,top1,top5,mrr\n";
    throw error;
  });
  const splitText = await fs.readFile(path.join(args.results, "by_split.csv"), "utf8");
  const rawText = await fs.readFile(path.join(args.results, "raw_results.csv"), "utf8");
  const cleanText = await fs.readFile(path.join(args.results, "clean_results.csv"), "utf8");
  const failureText = await fs.readFile(path.join(args.results, "failure_cases.csv"), "utf8");
  const rawImportText = literalizeCsvColumn(rawText, "candidate_formula");
  const failureImportText = literalizeCsvColumn(failureText, "candidate_formula");
  const comparison = JSON.parse(await fs.readFile(path.join(args.results, "paired_comparison.json"), "utf8"));
  const quality = JSON.parse(await fs.readFile(path.join(args.validation, "dataset_quality.json"), "utf8"));
  const cleanSummary = JSON.parse(await fs.readFile(path.join(args.results, "clean_summary.json"), "utf8"));

  const workbook = await Workbook.fromCSV(summaryText, { sheetName: "Summary" });
  await workbook.fromCSV(depthText, { sheetName: "ByDepth" });
  await workbook.fromCSV(errorText, { sheetName: "ByError" });
  await workbook.fromCSV(familyText, { sheetName: "ByFamily" });
  await workbook.fromCSV(topologyText, { sheetName: "ByTopology" });
  await workbook.fromCSV(splitText, { sheetName: "BySplit" });
  await workbook.fromCSV(rawImportText, { sheetName: "RawResults" });
  await workbook.fromCSV(cleanText, { sheetName: "CleanBooks" });
  await workbook.fromCSV(failureImportText, { sheetName: "Failures" });
  // Workbook.fromCSV interprets leading '=' as executable formulas. Candidate
  // repairs are evidence text and must remain literal, auditable strings.
  restoreLiteralColumn(workbook, "RawResults", rawText, "candidate_formula");
  restoreLiteralColumn(workbook, "Failures", failureText, "candidate_formula");
  const readme = workbook.worksheets.add("README");
  readme.showGridLines = false;
  readme.getRange("A1:F1").merge();
  readme.getRange("A1").values = [["FormulaGuard 实验结果工作簿"]];
  readme.getRange("A1:F1").format = {
    fill: "#0B2545",
    font: { name: "Microsoft YaHei", size: 16, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
  };
  readme.getRange("A3:B13").values = [
    ["字段", "内容"],
    ["数据总实例", quality.total],
    ["有效实例", quality.valid],
    ["排除实例", quality.excluded],
    ["数据有效率", quality.valid_rate],
    ["最强无真值基线", comparison.strongest_no_oracle_baseline],
    ["FormulaGuard MRR差", comparison.mean_mrr_difference],
    ["Bootstrap 95% CI", JSON.stringify(comparison.bootstrap_95_ci)],
    ["干净表警报率", cleanSummary.alarm_rate],
    ["结果性质", "当前代码与当前数据版本的实测结果；不是获奖保证"],
    ["论文纪律", "合成数据、真实数据和有真值上界必须分开报告"],
  ];
  readme.getRange("A3:B3").format = { fill: "#2E74B5", font: { bold: true, color: "#FFFFFF" } };
  readme.getRange("A3:B13").format.font = { name: "Microsoft YaHei", size: 10 };
  readme.getRange("A3:B13").format.borders = { preset: "all", style: "thin", color: "#CBD5E1" };
  readme.getRange("A:A").format.columnWidth = 24;
  readme.getRange("B:B").format.columnWidth = 70;
  readme.getRange("B7").format.numberFormat = "0.0%";
  readme.getRange("B9").format.numberFormat = "0.0000";
  readme.getRange("B11").format.numberFormat = "0.0%";

  const summary = workbook.worksheets.getItem("Summary");
  styleTabularSheet(summary, "N", rowCount(summaryText), { A: 24, B: 11, C: 11, D: 11, E: 11, F: 11, G: 13, H: 13, I: 11, J: 14, K: 18, L: 18, M: 15, N: 15 });
  summary.getRange(`C2:L${rowCount(summaryText)}`).format.numberFormat = "0.0000";
  summary.getRange(`C2:F${rowCount(summaryText)}`).conditionalFormats.add("colorScale", {
    criteria: [
      { type: "lowestValue", color: "#FEE2E2" },
      { type: "percentile", value: 50, color: "#FEF3C7" },
      { type: "highestValue", color: "#DCFCE7" },
    ],
  });
  styleTabularSheet(workbook.worksheets.getItem("ByDepth"), "F", rowCount(depthText), { A: 14, B: 24, C: 12, D: 12, E: 12, F: 12 });
  styleTabularSheet(workbook.worksheets.getItem("ByError"), "F", rowCount(errorText), { A: 28, B: 24, C: 12, D: 12, E: 12, F: 12 });
  styleTabularSheet(workbook.worksheets.getItem("ByFamily"), "F", rowCount(familyText), { A: 18, B: 24, C: 12, D: 12, E: 12, F: 12 });
  styleTabularSheet(workbook.worksheets.getItem("ByTopology"), "F", rowCount(topologyText), { A: 24, B: 24, C: 12, D: 12, E: 12, F: 12 });
  styleTabularSheet(workbook.worksheets.getItem("BySplit"), "F", rowCount(splitText), { A: 18, B: 24, C: 12, D: 12, E: 12, F: 12 });
  styleTabularSheet(workbook.worksheets.getItem("RawResults"), "AC", rowCount(rawText), { A: 30, B: 18, C: 24, D: 16, E: 28, F: 14, G: 12, H: 12, I: 14, J: 24, K: 10, L: 10, M: 10, N: 10, O: 12, P: 12, Q: 14, R: 45, S: 14, T: 18, U: 18, V: 14, W: 14, X: 16, Y: 16, Z: 16, AA: 16, AB: 24, AC: 24 });
  styleTabularSheet(workbook.worksheets.getItem("CleanBooks"), "G", rowCount(cleanText), { A: 24, B: 18, C: 14, D: 16, E: 24, F: 16, G: 12 });
  styleTabularSheet(workbook.worksheets.getItem("Failures"), "L", rowCount(failureText), { A: 30, B: 18, C: 24, D: 16, E: 28, F: 14, G: 14, H: 18, I: 24, J: 16, K: 12, L: 45 });

  const previewDir = path.join(args.results, "workbook_previews");
  await fs.mkdir(previewDir, { recursive: true });
  // Full evaluation has more than twelve thousand RawResults rows. Rendering
  // an entire raw-data sheet produces a hundreds-of-thousands-pixel image and
  // is both unnecessary for visual QA and rejected by the renderer. Preview a
  // bounded, representative range while keeping every row in the XLSX export.
  const previewRanges = {
    README: "A1:B13",
    Summary: `A1:N${Math.min(rowCount(summaryText), 20)}`,
    ByDepth: `A1:F${Math.min(rowCount(depthText), 50)}`,
    ByError: `A1:F${Math.min(rowCount(errorText), 100)}`,
    ByFamily: `A1:F${Math.min(rowCount(familyText), 100)}`,
    ByTopology: `A1:F${Math.min(rowCount(topologyText), 100)}`,
    BySplit: `A1:F${Math.min(rowCount(splitText), 20)}`,
    CleanBooks: `A1:G${Math.min(rowCount(cleanText), 60)}`,
    Failures: `A1:L${Math.min(rowCount(failureText), 80)}`,
    RawResults: `A1:AC${Math.min(rowCount(rawText), 40)}`,
  };
  for (const sheetName of ["README", "Summary", "ByDepth", "ByError", "ByFamily", "ByTopology", "BySplit", "CleanBooks", "Failures", "RawResults"]) {
    const preview = await workbook.render({ sheetName, range: previewRanges[sheetName], scale: 1.0, format: "png" });
    await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  const inspect = await workbook.inspect({ kind: "workbook,sheet,table", maxChars: 8000, tableMaxRows: 15, tableMaxCols: 18 });
  await fs.writeFile(path.join(args.results, "results_workbook_inspection.ndjson"), inspect.ndjson, "utf8");
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
  await fs.writeFile(path.join(args.results, "results_workbook_formula_errors.ndjson"), errors.ndjson, "utf8");

  await fs.mkdir(path.dirname(args.output), { recursive: true });
  const blob = await SpreadsheetFile.exportXlsx(workbook);
  await blob.save(args.output);
  await fs.rm(`${args.output}.inspect.ndjson`, { force: true });
  console.log(args.output);
}

await main();
