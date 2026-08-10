import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function parseArgs(argv) {
  const args = { output: path.join(ROOT, "data", "scaling"), sizes: [100, 500, 1000, 5000] };
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i] === "--output") args.output = path.resolve(argv[++i]);
    else if (argv[i] === "--sizes") args.sizes = argv[++i].split(",").map(Number);
    else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  return args;
}

async function build(targetFormulaCount, outputDir) {
  const detailRows = Math.max(10, Math.floor((targetFormulaCount - 10) / 2));
  const first = 5;
  const last = first + detailRows - 1;
  const summary = last + 2;
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("ScaleModel");
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(4);
  sheet.getRange("A1:F1").merge();
  sheet.getRange("A1").values = [[`FormulaGuard scaling benchmark: target ${targetFormulaCount} formulas`]];
  sheet.getRange("A2:C2").values = [["参数", 0.08, 0.02]];
  sheet.getRange("A4:F4").values = [["条目", "数量", "单价", "基础结果", "调整结果", "汇总链"]];
  const inputs = [];
  for (let i = 0; i < detailRows; i += 1) inputs.push([`item_${i + 1}`, 2 + (i % 17), 5 + ((i * 13) % 47) / 2]);
  sheet.getRange(`A${first}:C${last}`).values = inputs;
  sheet.getRange(`D${first}`).formulas = [[`=B${first}*C${first}`]];
  sheet.getRange(`D${first}:D${last}`).fillDown();
  sheet.getRange(`E${first}`).formulas = [[`=D${first}*(1+$B$2)`]];
  sheet.getRange(`E${first}:E${last}`).fillDown();
  sheet.getRange(`D${summary}`).formulas = [[`=SUM(D${first}:D${last})`]];
  sheet.getRange(`E${summary}`).formulas = [[`=SUM(E${first}:E${last})`]];
  sheet.getRange(`E${summary + 1}`).formulas = [[`=AVERAGE(E${first}:E${last})`]];
  sheet.getRange(`E${summary + 2}`).formulas = [[`=MAX(E${first}:E${last})`]];
  sheet.getRange(`E${summary + 3}`).formulas = [[`=MIN(E${first}:E${last})`]];
  sheet.getRange(`F${summary}`).formulas = [[`=E${summary}+E${summary + 1}`]];
  sheet.getRange(`F${summary + 1}`).formulas = [[`=F${summary}+E${summary + 2}`]];
  sheet.getRange(`F${summary + 2}`).formulas = [[`=F${summary + 1}-E${summary + 3}`]];
  sheet.getRange(`F${summary + 3}`).formulas = [[`=F${summary + 2}*(1+$C$2)`]];
  sheet.getRange(`F${summary + 4}`).formulas = [[`=F${summary + 3}+D${summary}`]];
  sheet.getRange(`A1:F${summary + 4}`).format.font = { name: "Microsoft YaHei", size: 9 };
  sheet.getRange("A1:F1").format = { fill: "#0B2545", font: { bold: true, color: "#FFFFFF", size: 14 }, horizontalAlignment: "center" };
  sheet.getRange("A4:F4").format = { fill: "#2E74B5", font: { bold: true, color: "#FFFFFF" } };
  sheet.getRange(`A${first}:C${last}`).format.fill = "#FFF8E8";
  sheet.getRange(`D${first}:F${summary + 4}`).format.fill = "#F4F6F9";
  sheet.getRange("A:A").format.columnWidth = 18;
  sheet.getRange("B:F").format.columnWidth = 14;
  const filePath = path.join(outputDir, `scale_${targetFormulaCount}.xlsx`);
  const blob = await SpreadsheetFile.exportXlsx(workbook);
  await blob.save(filePath);
  await fs.rm(`${filePath}.inspect.ndjson`, { force: true });
  return { target_formula_count: targetFormulaCount, detail_rows: detailRows, workbook: path.basename(filePath) };
}

async function main() {
  const args = parseArgs(process.argv);
  await fs.mkdir(args.output, { recursive: true });
  const records = [];
  for (const size of args.sizes) records.push(await build(size, args.output));
  await fs.writeFile(path.join(args.output, "scaling_manifest.json"), JSON.stringify({ version: "0.1.0", records }, null, 2), "utf8");
  console.log(JSON.stringify(records));
}

await main();

