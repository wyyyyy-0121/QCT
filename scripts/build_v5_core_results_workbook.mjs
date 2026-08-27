import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

function columnName(index) {
  let value = index + 1;
  let result = "";
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') { field += '"'; index += 1; }
      else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ',') { row.push(field); field = ""; }
    else if (char === '\n') { row.push(field.replace(/\r$/, "")); rows.push(row); row = []; field = ""; }
    else field += char;
  }
  if (field || row.length) { row.push(field.replace(/\r$/, "")); rows.push(row); }
  return rows.filter(values => values.some(value => value !== ""));
}

function typed(value, header) {
  if (value === "true") return true;
  if (value === "false") return false;
  if (/^(events|rank|formula_count)$/.test(header) && /^-?\d+$/.test(value)) return Number(value);
  if (/^(top|mrr|exam|macro|weakest|candidate|exact|clean)/.test(header) && value !== "" && Number.isFinite(Number(value))) return Number(value);
  return value.startsWith("=") ? `'${value}` : value;
}

function styleTable(sheet, range, headerRange) {
  range.format.font = { name: "Aptos", size: 10, color: "#243047" };
  headerRange.format = {
    fill: "#163A5F",
    font: { name: "Aptos Display", size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#A9B7C6" },
  };
  range.format.borders = {
    insideHorizontal: { style: "thin", color: "#DCE3EA" },
    bottom: { style: "thin", color: "#A9B7C6" },
  };
}

async function main() {
  const args = process.argv.slice(2);
  const value = flag => args[args.indexOf(flag) + 1];
  const results = value("--results");
  const output = value("--output");
  const summary = JSON.parse(await fs.readFile(path.join(results, "summary.json"), "utf8"));
  const summaryCsv = parseCsv(await fs.readFile(path.join(results, "summary.csv"), "utf8").then(text => text.replace(/^\uFEFF/, "")));
  const byErrorCsv = parseCsv(await fs.readFile(path.join(results, "by_error.csv"), "utf8").then(text => text.replace(/^\uFEFF/, "")));
  const eventPath = path.join(results, "event_results.csv");
  let eventCsv = [];
  try { eventCsv = parseCsv((await fs.readFile(eventPath, "utf8")).replace(/^\uFEFF/, "")); } catch {}

  const workbook = Workbook.create();
  const overview = workbook.worksheets.add("Overview");
  const summarySheet = workbook.worksheets.add("MethodSummary");
  const errorSheet = workbook.worksheets.add("ByErrorType");
  const rawSheet = workbook.worksheets.add("EventResults");
  const protocol = workbook.worksheets.add("Protocol");
  for (const sheet of [overview, summarySheet, errorSheet, rawSheet, protocol]) sheet.showGridLines = false;

  overview.getRange("A1:H2").merge();
  overview.getRange("A1").values = [["FormulaGuard V5-Core Experiment Evidence"]];
  overview.getRange("A1:H2").format = {
    fill: "#0E2A47", font: { name: "Aptos Display", size: 20, bold: true, color: "#FFFFFF" },
    verticalAlignment: "center", horizontalAlignment: "left",
  };
  overview.getRange("A4:B8").values = [
    ["Architecture", "Candidate-centric multi-evidence responsibility"],
    ["Primary comparison", "V5-Core Rule / Learned vs frozen V4"],
    ["Prediction-label isolation", "Verified by completion receipt before scoring"],
    ["Current evidence tier", output.includes("smoke") ? "Engineering smoke only" : "Development or locked evaluation"],
    ["Interpretation", "Do not treat development results as independent conclusions"],
  ];
  overview.getRange("A4:A8").format = { fill: "#DCEAF7", font: { bold: true, color: "#163A5F" } };
  overview.getRange("A4:B8").format.wrapText = true;
  overview.getRange("A4:B8").format.borders = { preset: "outside", style: "thin", color: "#A9B7C6" };
  overview.getRange("A10:H10").merge();
  overview.getRange("A10").values = [["Headline metrics"]];
  overview.getRange("A10:H10").format = { fill: "#2C6E91", font: { bold: true, color: "#FFFFFF" } };
  const headline = Object.entries(summary.summary).map(([method, metrics]) => [
    method, metrics.top5, metrics.mrr, metrics.macro_top5, metrics.weakest_type_top5,
    metrics.candidate_coverage_32, metrics.exact_repair,
    summary.clean?.[method]?.false_alarm_rate ?? null,
  ]);
  overview.getRange(`A11:H${11 + headline.length}`).values = [["Method", "Top-5", "MRR", "Macro Top-5", "Weakest Top-5", "Coverage@32", "Exact Repair", "Clean FPR"], ...headline];
  styleTable(overview, overview.getRange(`A11:H${11 + headline.length}`), overview.getRange("A11:H11"));
  overview.getRange(`B12:B${11 + headline.length}`).format.numberFormat = "0.0%";
  overview.getRange(`C12:C${11 + headline.length}`).format.numberFormat = "0.0000";
  overview.getRange(`D12:H${11 + headline.length}`).format.numberFormat = "0.0%";
  overview.freezePanes.freezeRows(2);

  const sheets = [[summarySheet, summaryCsv], [errorSheet, byErrorCsv], [rawSheet, eventCsv]];
  for (const [sheet, rows] of sheets) {
    if (!rows.length) { sheet.getRange("A1").values = [["No rows available"]]; continue; }
    const headers = rows[0];
    const matrix = rows.map((row, rowIndex) => row.map((cell, colIndex) => rowIndex === 0 ? cell : typed(cell, headers[colIndex])));
    const lastColumn = columnName(headers.length - 1);
    sheet.getRange(`A1:${lastColumn}${matrix.length}`).values = matrix;
    styleTable(sheet, sheet.getRange(`A1:${lastColumn}${matrix.length}`), sheet.getRange(`A1:${lastColumn}1`));
    sheet.freezePanes.freezeRows(1);
    sheet.getRange(`A1:${lastColumn}${Math.min(matrix.length, 200)}`).format.autofitColumns();
    for (let col = 0; col < headers.length; col += 1) {
      const range = sheet.getRange(`${columnName(col)}1:${columnName(col)}${matrix.length}`);
      const headerLength = String(headers[col] ?? "").length;
      const wideHeaders = new Set(["instance_id", "mutation_type", "error_type", "regime", "topology"]);
      range.format.columnWidth = wideHeaders.has(headers[col])
        ? Math.min(28, Math.max(18, headerLength + 5))
        : Math.min(28, Math.max(11, headerLength + 3));
    }
  }

  protocol.getRange("A1:F2").merge();
  protocol.getRange("A1").values = [["Protocol and reproducibility notes"]];
  protocol.getRange("A1:F2").format = { fill: "#0E2A47", font: { size: 16, bold: true, color: "#FFFFFF" } };
  protocol.getRange("A4:B10").values = [
    ["Model", "V5-Core candidate-first responsibility model"],
    ["Rule head", "sqrt(two strongest independent evidence families) × exception and harm safeguards"],
    ["Learned head", "Sign-constrained pairwise linear ranker on the same evidence"],
    ["Random seed", 20260827],
    ["Worker default", 24],
    ["Label isolation", "Predictions are atomically completed before labels are read"],
    ["Formula-text safety", "Literal formulas are exported as text with a leading apostrophe"],
  ];
  protocol.getRange("A4:A10").format = { fill: "#DCEAF7", font: { bold: true, color: "#163A5F" } };
  protocol.getRange("A4:B10").format.wrapText = true;
  protocol.getRange("A4:B10").format.borders = { preset: "outside", style: "thin", color: "#A9B7C6" };
  protocol.getRange("A1:B12").format.columnWidth = 28;

  overview.getRange("A1:B20").format.columnWidth = 28;
  overview.getRange("A1:H20").format.wrapText = true;
  await fs.mkdir(path.dirname(output), { recursive: true });
  const exported = await SpreadsheetFile.exportXlsx(workbook);
  await exported.save(output);

  const inspection = await workbook.inspect({ kind: "table", range: "Overview!A1:H20", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 8 });
  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 300 }, summary: "final formula error scan" });
  console.log(inspection.ndjson);
  console.log(errors.ndjson);
  const previewRoot = path.join(path.dirname(output), ".v5_core_previews");
  await fs.mkdir(previewRoot, { recursive: true });
  for (const [sheetName, range] of [["Overview", "A1:H20"], ["MethodSummary", "A1:L20"], ["ByErrorType", "A1:C30"], ["EventResults", "A1:J30"], ["Protocol", "A1:F12"]]) {
    const preview = await workbook.render({ sheetName, range, scale: 1, format: "png" });
    await fs.writeFile(path.join(previewRoot, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  console.log(output);
}

await main();
