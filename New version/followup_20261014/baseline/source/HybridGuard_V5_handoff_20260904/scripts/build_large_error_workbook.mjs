import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = process.argv[2];
if (!outputDir) throw new Error("usage: node build_large_error_workbook.mjs OUTPUT_DIRECTORY");

const regions = ["North", "Central", "East", "South", "West"];
const rowCount = 1500;

function lcg(seed) {
  let state = seed >>> 0;
  return () => {
    state = (1664525 * state + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function correctFormula(row) {
  return `=B${row}*C${row}*(1-D${row})*(1-G${row})-B${row}*E${row}-F${row}`;
}

function wrongFormula(row, mutation) {
  const variants = {
    plus_cost: `=B${row}*C${row}*(1-D${row})*(1-G${row})+B${row}*E${row}-F${row}`,
    flip_discount: `=B${row}*C${row}*(1+D${row})*(1-G${row})-B${row}*E${row}-F${row}`,
    multiplier_085: `=B${row}*C${row}*(1-D${row})*(1-G${row})*0.85-B${row}*E${row}-F${row}`,
    omit_shipping: `=B${row}*C${row}*(1-D${row})*(1-G${row})-B${row}*E${row}`,
    flip_tax: `=B${row}*C${row}*(1-D${row})*(1+G${row})-B${row}*E${row}-F${row}`,
  };
  if (!variants[mutation]) throw new Error(`unknown mutation: ${mutation}`);
  return variants[mutation];
}

function sparseGroups(seed, count) {
  const random = lcg(seed);
  const mutations = ["plus_cost", "flip_discount", "omit_shipping", "flip_tax", "multiplier_085"];
  const selected = [];
  const used = new Set();
  while (selected.length < count) {
    const sheet = regions[Math.floor(random() * regions.length)];
    const row = 20 + Math.floor(random() * (rowCount - 39));
    const key = `${sheet}!I${row}`;
    if (used.has(key)) continue;
    used.add(key);
    selected.push({
      group_id: `sparse-${seed}-${String(selected.length + 1).padStart(3, "0")}`,
      kind: "singleton", sheet, start: row, end: row,
      mutation: mutations[Math.floor(random() * mutations.length)],
    });
  }
  return selected;
}

const scenarios = [
  { name: "sparse_seed101", family: "sparse", seed: 101, groups: sparseGroups(101, 12) },
  { name: "sparse_seed202", family: "sparse", seed: 202, groups: sparseGroups(202, 30) },
  { name: "sparse_seed303", family: "sparse", seed: 303, groups: sparseGroups(303, 60) },
  { name: "systemic_seed404", family: "systemic", seed: 404, groups: [
    { group_id: "sys404-north-150", kind: "contiguous-150", sheet: "North", start: 180, end: 329, mutation: "flip_discount" },
    { group_id: "sys404-south-500", kind: "contiguous-500", sheet: "South", start: 700, end: 1199, mutation: "plus_cost" },
    { group_id: "sys404-west-column", kind: "whole-column-1499", sheet: "West", start: 2, end: 1500, mutation: "multiplier_085" },
  ] },
  { name: "systemic_seed505", family: "systemic", seed: 505, groups: [
    { group_id: "sys505-central-100", kind: "contiguous-100", sheet: "Central", start: 90, end: 189, mutation: "omit_shipping" },
    { group_id: "sys505-east-400", kind: "contiguous-400", sheet: "East", start: 450, end: 849, mutation: "flip_tax" },
    { group_id: "sys505-south-900", kind: "contiguous-900", sheet: "South", start: 590, end: 1489, mutation: "flip_discount" },
  ] },
  { name: "systemic_seed606", family: "systemic", seed: 606, groups: [
    { group_id: "sys606-north-column", kind: "whole-column-1499", sheet: "North", start: 2, end: 1500, mutation: "multiplier_085" },
    { group_id: "sys606-central-250", kind: "contiguous-250", sheet: "Central", start: 300, end: 549, mutation: "plus_cost" },
    { group_id: "sys606-west-350", kind: "contiguous-350", sheet: "West", start: 900, end: 1249, mutation: "omit_shipping" },
  ] },
];

function matchingGroup(groups, sheet, row) {
  return groups.find((group) => group.sheet === sheet && row >= group.start && row <= group.end);
}

async function buildScenario(scenario) {
  const workbook = Workbook.create();
  const random = lcg(scenario.seed);
  const errors = [];
  const truthGroups = scenario.groups.map((group) => ({ group_id: group.group_id, kind: group.kind, cells: [] }));
  const truthLookup = new Map(truthGroups.map((group) => [group.group_id, group]));

  for (let sheetIndex = 0; sheetIndex < regions.length; sheetIndex += 1) {
    const region = regions[sheetIndex];
    const sheet = workbook.worksheets.add(region);
    sheet.showGridLines = false;
    sheet.freezePanes.freezeRows(1);
    const rows = [["Order ID", "Units", "Unit Price", "Discount Rate", "Unit Cost", "Shipping", "Tax Rate", "Region Code", "Net Profit", "Audit Channel"]];
    for (let row = 2; row <= rowCount; row += 1) {
      const units = 5 + Math.floor(random() * 96);
      const price = 20 + Math.floor(random() * 480) + Math.floor(random() * 10) / 10;
      const discount = Math.floor(random() * 8) * 0.01;
      const unitCost = 8 + Math.floor(random() * 120) + Math.floor(random() * 20) / 20;
      const shipping = 3 + Math.floor(random() * 18);
      const tax = 0.03 + Math.floor(random() * 5) * 0.005;
      const group = matchingGroup(scenario.groups, region, row);
      const formula = group ? wrongFormula(row, group.mutation) : correctFormula(row);
      const cell = `${region}!I${row}`;
      if (group) {
        errors.push({ cell, kind: group.kind, group_id: group.group_id, mutation: group.mutation, wrong_formula: formula, correct_formula: correctFormula(row) });
        truthLookup.get(group.group_id).cells.push(cell);
      }
      rows.push([
        `${region.slice(0, 2).toUpperCase()}-${String(row - 1).padStart(5, "0")}`,
        units, price, discount, unitCost, shipping, tax, region, formula,
        row === 2 ? `=SUM(I2:I${rowCount})` : row === 3 ? `=AVERAGE(I2:I${rowCount})` : "standard",
      ]);
    }
    sheet.getRange(`A1:J${rowCount}`).values = rows;
    sheet.getRange("A1:J1").format = { fill: "#16324F", font: { bold: true, color: "#FFFFFF" }, rowHeight: 24 };
    sheet.getRange(`A2:A${rowCount}`).format.numberFormat = "@";
    sheet.getRange(`B2:B${rowCount}`).format.numberFormat = "#,##0";
    sheet.getRange(`C2:C${rowCount}`).format.numberFormat = "$#,##0.00";
    sheet.getRange(`D2:D${rowCount}`).format.numberFormat = "0.0%";
    sheet.getRange(`E2:F${rowCount}`).format.numberFormat = "$#,##0.00";
    sheet.getRange(`G2:G${rowCount}`).format.numberFormat = "0.0%";
    sheet.getRange(`I2:I${rowCount}`).format.numberFormat = "$#,##0.00";
    sheet.getRange("J2:J3").format.numberFormat = "$#,##0.00";
    sheet.getRange(`A1:J${rowCount}`).format.font = { name: "Aptos", size: 10 };
    sheet.getRange("A1:J1").format.font = { name: "Aptos Display", size: 10, bold: true, color: "#FFFFFF" };
    [16, 10, 14, 14, 13, 12, 11, 14, 18, 22].forEach((width, col) => sheet.getRangeByIndexes(0, col, rowCount, 1).format.columnWidth = width);
  }

  const workbookPath = path.join(outputDir, `${scenario.name}.xlsx`);
  const truthPath = path.join(outputDir, `${scenario.name}_truth.json`);
  const blob = await SpreadsheetFile.exportXlsx(workbook);
  await blob.save(workbookPath);
  await fs.writeFile(truthPath, JSON.stringify({
    protocol: "multi_scenario_formula_error_suite_v2", scenario: scenario.name,
    family: scenario.family, seed: scenario.seed,
    generated_cells: regions.length * rowCount * 10,
    formula_cells: regions.length * (rowCount - 1) + regions.length * 2,
    error_cells: errors.length,
    error_rate: errors.length / (regions.length * (rowCount - 1) + regions.length * 2),
    parallel_sheets: regions, groups: truthGroups, errors,
  }, null, 2), "utf8");

  for (const region of regions) {
    const preview = await workbook.render({ sheetName: region, range: "A1:J14", scale: 0.9, format: "png" });
    await fs.writeFile(path.join(outputDir, `${scenario.name}_${region}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  const firstGroup = scenario.groups[0];
  const start = Math.max(1, firstGroup.start - 3);
  const end = Math.min(rowCount, firstGroup.start + 5);
  const boundary = await workbook.render({ sheetName: firstGroup.sheet, range: `A${start}:J${end}`, scale: 1.0, format: "png" });
  await fs.writeFile(path.join(outputDir, `${scenario.name}_error_boundary.png`), new Uint8Array(await boundary.arrayBuffer()));

  const check = await workbook.inspect({ kind: "table", sheetId: firstGroup.sheet, range: `A${start}:J${end}`, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 12, maxChars: 6000 });
  const errorScan = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: `${scenario.name} formula error scan` });
  console.log(JSON.stringify({ scenario: scenario.name, family: scenario.family, errors: errors.length, groups: truthGroups.length, check: check.ndjson, formulaErrorScan: errorScan.ndjson }));
  return { scenario: scenario.name, family: scenario.family, seed: scenario.seed, workbook: workbookPath, truth: truthPath, errors: errors.length, groups: truthGroups.length };
}

await fs.mkdir(outputDir, { recursive: true });
const manifest = [];
for (const scenario of scenarios) manifest.push(await buildScenario(scenario));
await fs.writeFile(path.join(outputDir, "suite_manifest.json"), JSON.stringify({ protocol: "multi_scenario_formula_error_suite_v2", workbook_count: manifest.length, scenarios: manifest }, null, 2), "utf8");
