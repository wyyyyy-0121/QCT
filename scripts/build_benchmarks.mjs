import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function parseArgs(argv) {
  const args = { mode: "quick", output: path.join(ROOT, "data", "propagationbench") };
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i] === "--mode") args.mode = argv[++i];
    else if (argv[i] === "--output") args.output = path.resolve(argv[++i]);
    else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  if (!new Set(["smoke", "quick", "full"]).has(args.mode)) throw new Error(`Invalid mode: ${args.mode}`);
  return args;
}

const FAMILIES = [
  { id: "budget", split: "development", title: "部门预算", unit: "项目", qty: "数量", rate: "单价" },
  { id: "sales", split: "development", title: "月度销售", unit: "产品", qty: "销量", rate: "单价" },
  { id: "inventory", split: "validation", title: "库存成本", unit: "物料", qty: "库存量", rate: "单位成本" },
  { id: "grades", split: "validation", title: "课程成绩", unit: "学生", qty: "学分", rate: "成绩" },
  { id: "experiment", split: "test", title: "实验测量", unit: "样本", qty: "测量次数", rate: "测量值" },
  { id: "energy", split: "test", title: "能耗统计", unit: "设备", qty: "运行时长", rate: "单位能耗" },
  { id: "schedule", split: "test", title: "项目工时", unit: "任务", qty: "人数", rate: "工时" },
  { id: "invoice", split: "test", title: "发票结算", unit: "条目", qty: "数量", rate: "含税单价" },
  { id: "attendance", split: "test", title: "出勤统计", unit: "班级", qty: "应到人数", rate: "出勤率" },
  { id: "fundraising", split: "test", title: "活动筹款", unit: "渠道", qty: "参与人数", rate: "人均金额" },
];

function workbookSpec(family, variant) {
  const detailCount = 10 + ((variant + FAMILIES.findIndex(x => x.id === family.id)) % 5);
  const first = 5;
  const last = first + detailCount - 1;
  const summary = last + 2;
  const seed = 2026081000 + FAMILIES.findIndex(x => x.id === family.id) * 100 + variant;
  const rows = [];
  for (let i = 0; i < detailCount; i += 1) {
    const qty = 3 + ((seed + i * 7) % 17);
    const rate = 8 + ((seed * 3 + i * 11) % 43) + ((i % 3) * 0.25);
    rows.push([`${family.unit}${String(i + 1).padStart(2, "0")}`, qty, rate]);
  }
  const formulas = {};
  for (let r = first; r <= last; r += 1) {
    formulas[`D${r}`] = `=B${r}*C${r}`;
    formulas[`E${r}`] = `=D${r}*(1+$B$2)`;
  }
  formulas[`D${summary}`] = `=SUM(D${first}:D${last})`;
  formulas[`E${summary}`] = `=SUM(E${first}:E${last})`;
  formulas[`E${summary + 1}`] = `=E${summary}*(1+$B$2)`;
  formulas[`E${summary + 2}`] = `=AVERAGE(E${first}:E${last})`;
  formulas[`E${summary + 3}`] = `=MAX(E${first}:E${last})`;
  formulas[`E${summary + 4}`] = `=MIN(E${first}:E${last})`;
  formulas[`F${summary}`] = `=E${summary + 1}+E${summary + 2}`;
  formulas[`F${summary + 1}`] = `=F${summary}+E${summary + 3}`;
  formulas[`F${summary + 2}`] = `=F${summary + 1}-E${summary + 4}`;
  formulas[`F${summary + 3}`] = `=F${summary + 2}*(1+$C$2)`;
  formulas[`F${summary + 4}`] = `=F${summary + 3}+D${summary}`;
  return { family, variant, detailCount, first, last, summary, seed, rows, formulas, sink: `F${summary + 4}` };
}

function mutationCatalog(spec) {
  const { first, last, summary: s } = spec;
  const deepRowA = Math.min(last, first + 2);
  const deepRowB = Math.min(last, first + 4);
  const deepRowC = Math.min(last, first + 6);
  const items = [
    { id: "M1_deep", type: "M1_reference_shift", expectedDepth: "deep", cell: `D${deepRowA}`, formula: `=B${deepRowA - 1}*C${deepRowA}` },
    { id: "M2_deep", type: "M2_range_boundary", expectedDepth: "deep", cell: `E${s}`, formula: `=SUM(E${first}:E${last - 1})` },
    { id: "M3_medium", type: "M3_operator", expectedDepth: "medium", cell: `F${s}`, formula: `=E${s + 1}-E${s + 2}` },
    { id: "M4_medium", type: "M4_function", expectedDepth: "medium", cell: `E${s + 3}`, formula: `=MIN(E${first}:E${last})` },
    { id: "M5_deep", type: "M5_absolute_reference", expectedDepth: "deep", cell: `E${deepRowB}`, formula: `=D${deepRowB}*(1+B${Math.max(3, deepRowB - 3)})` },
    { id: "M6_shallow", type: "M6_copy_offset", expectedDepth: "shallow", cell: `F${s + 3}`, formula: `=F${s + 1}*(1+$C$2)` },

    { id: "M1_medium", type: "M1_reference_shift", expectedDepth: "medium", cell: `F${s}`, formula: `=E${s}+E${s + 2}` },
    { id: "M1_shallow", type: "M1_reference_shift", expectedDepth: "shallow", cell: `F${s + 3}`, formula: `=F${s + 1}*(1+$C$2)` },
    { id: "M2_medium", type: "M2_range_boundary", expectedDepth: "medium", cell: `E${s + 2}`, formula: `=AVERAGE(E${first}:E${last - 1})` },
    { id: "M2_shallow", type: "M2_range_boundary", expectedDepth: "shallow", cell: `D${s}`, formula: `=SUM(D${first}:D${last - 1})` },
    { id: "M3_deep", type: "M3_operator", expectedDepth: "deep", cell: `D${deepRowC}`, formula: `=B${deepRowC}+C${deepRowC}` },
    { id: "M3_shallow", type: "M3_operator", expectedDepth: "shallow", cell: `F${s + 3}`, formula: `=F${s + 2}/(1+$C$2)` },
    { id: "M4_deep", type: "M4_function", expectedDepth: "deep", cell: `E${deepRowC}`, formula: `=SUM(D${deepRowC},$B$2)` },
    { id: "M4_medium2", type: "M4_function", expectedDepth: "medium", cell: `E${s + 2}`, formula: `=SUM(E${first}:E${last})` },
    { id: "M5_medium", type: "M5_absolute_reference", expectedDepth: "medium", cell: `E${s + 1}`, formula: `=E${s}*(1+B${s})` },
    { id: "M5_shallow", type: "M5_absolute_reference", expectedDepth: "shallow", cell: `F${s + 3}`, formula: `=F${s + 2}*(1+C${last})` },
    { id: "M6_deep", type: "M6_copy_offset", expectedDepth: "deep", cell: `D${deepRowB}`, formula: `=B${deepRowB}*C${deepRowB - 1}` },
    { id: "M6_medium", type: "M6_copy_offset", expectedDepth: "medium", cell: `F${s}`, formula: `=E${s + 1}+E${s + 3}` },
  ];
  return items.filter(item => spec.formulas[item.cell] && spec.formulas[item.cell] !== item.formula);
}

function styleWorkbook(sheet, spec) {
  const end = spec.summary + 4;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(4);
  sheet.getRange("A1:F1").format = {
    fill: "#0B2545",
    font: { bold: true, color: "#FFFFFF", size: 16 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
  sheet.getRange("A1:F1").format.rowHeight = 28;
  sheet.getRange("A4:F4").format = {
    fill: "#2E74B5",
    font: { bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    borders: { preset: "outside", style: "thin", color: "#1F4D78" },
  };
  sheet.getRange(`A${spec.first}:C${spec.last}`).format.fill = "#FFF8E8";
  sheet.getRange(`D${spec.first}:F${end}`).format.fill = "#F4F6F9";
  sheet.getRange(`A${spec.summary}:F${end}`).format.borders = { preset: "inside", style: "thin", color: "#CBD5E1" };
  sheet.getRange(`B${spec.first}:B${spec.last}`).format.numberFormat = "#,##0";
  sheet.getRange(`C${spec.first}:F${end}`).format.numberFormat = "#,##0.00";
  sheet.getRange("B2:C2").format.numberFormat = "0.0%";
  sheet.getRange("A:A").format.columnWidth = 18;
  sheet.getRange("B:C").format.columnWidth = 13;
  sheet.getRange("D:F").format.columnWidth = 16;
  sheet.getRange(`A1:F${end}`).format.font = { name: "Microsoft YaHei", size: 10 };
  sheet.getRange("A1:F1").format.font = { name: "Microsoft YaHei", size: 16, bold: true, color: "#FFFFFF" };
}

function buildWorkbook(spec, mutation = null) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("Model");
  sheet.getRange("A1:F1").merge();
  sheet.getRange("A1").values = [[`${spec.family.title} - FormulaGuard ${mutation ? "错误实例" : "正确模板"}`]];
  sheet.getRange("A2:C2").values = [["调整率", 0.08 + spec.variant * 0.002, 0.02]];
  sheet.getRange("A3:C3").values = [["说明", "B2为主要调整率", "C2为末级修正率"]];
  sheet.getRange("A4:F4").values = [[spec.family.unit, spec.family.qty, spec.family.rate, "基础结果", "调整结果", "汇总链"]];
  sheet.getRange(`A${spec.first}:C${spec.last}`).values = spec.rows;
  sheet.getRange(`A${spec.summary}:A${spec.summary + 4}`).values = [["基础合计"], ["调整后合计"], ["平均"], ["最大"], ["最小"]];

  const formulas = { ...spec.formulas };
  if (mutation) formulas[mutation.cell] = mutation.formula;
  for (let r = spec.first; r <= spec.last; r += 1) {
    sheet.getRange(`D${r}`).formulas = [[formulas[`D${r}`]]];
    sheet.getRange(`E${r}`).formulas = [[formulas[`E${r}`]]];
  }
  for (let r = spec.summary; r <= spec.summary + 4; r += 1) {
    if (formulas[`D${r}`]) sheet.getRange(`D${r}`).formulas = [[formulas[`D${r}`]]];
    if (formulas[`E${r}`]) sheet.getRange(`E${r}`).formulas = [[formulas[`E${r}`]]];
    if (formulas[`F${r}`]) sheet.getRange(`F${r}`).formulas = [[formulas[`F${r}`]]];
  }
  styleWorkbook(sheet, spec);
  return workbook;
}

async function sha256(filePath) {
  const data = await fs.readFile(filePath);
  return crypto.createHash("sha256").update(data).digest("hex");
}

async function exportWorkbook(workbook, filePath) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const blob = await SpreadsheetFile.exportXlsx(workbook);
  await blob.save(filePath);
  // artifact-tool may emit a neighboring diagnostic sidecar; the benchmark
  // keeps explicit verification files only under preview/.
  await fs.rm(`${filePath}.inspect.ndjson`, { force: true });
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

async function main() {
  const args = parseArgs(process.argv);
  await fs.mkdir(args.output, { recursive: true });
  const cleanDir = path.join(args.output, "clean");
  const mutantDir = path.join(args.output, "mutants");
  const previewDir = path.join(args.output, "preview");
  await Promise.all([fs.mkdir(cleanDir, { recursive: true }), fs.mkdir(mutantDir, { recursive: true }), fs.mkdir(previewDir, { recursive: true })]);

  const families = args.mode === "smoke"
    ? FAMILIES.filter(x => x.split === "development")
    : args.mode === "quick"
      ? FAMILIES.filter(x => x.split !== "test")
      : FAMILIES.filter(x => x.split === "test");
  const variants = args.mode === "full" ? 8 : args.mode === "quick" ? 2 : 1;
  const mutationCount = args.mode === "full" ? 18 : 6;
  const instances = [];
  const cleanRecords = [];
  let previewWritten = false;

  for (const family of families) {
    for (let variant = 0; variant < variants; variant += 1) {
      const spec = workbookSpec(family, variant);
      const cleanId = `${family.id}_v${variant}`;
      const cleanPath = path.join(cleanDir, `${cleanId}.xlsx`);
      const cleanWorkbook = buildWorkbook(spec);
      await exportWorkbook(cleanWorkbook, cleanPath);
      const cleanHash = await sha256(cleanPath);
      cleanRecords.push({ cleanId, family: family.id, data_split: family.split, variant, path: path.relative(args.output, cleanPath).replaceAll("\\", "/"), sha256: cleanHash });

      if (!previewWritten) {
        const inspection = await cleanWorkbook.inspect({ kind: "workbook,sheet,formula,table", maxChars: 8000, tableMaxRows: 30, tableMaxCols: 8 });
        await fs.writeFile(path.join(previewDir, "verification_first.ndjson"), inspection.ndjson, "utf8");
        const errors = await cleanWorkbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
        await fs.writeFile(path.join(previewDir, "formula_error_scan.ndjson"), errors.ndjson, "utf8");
        const rendered = await cleanWorkbook.render({ sheetName: "Model", autoCrop: "all", scale: 1.5, format: "png" });
        await fs.writeFile(path.join(previewDir, "clean_example.png"), new Uint8Array(await rendered.arrayBuffer()));
        previewWritten = true;
      }

      for (const mutation of mutationCatalog(spec).slice(0, mutationCount)) {
        const instanceId = `${cleanId}_${mutation.id}`;
        const mutantPath = path.join(mutantDir, `${instanceId}.xlsx`);
        const mutantWorkbook = buildWorkbook(spec, mutation);
        await exportWorkbook(mutantWorkbook, mutantPath);
        const mutantHash = await sha256(mutantPath);
        instances.push({
          instance_id: instanceId,
          template_family: family.id,
          data_split: family.split,
          variant,
          seed: spec.seed,
          clean_workbook: path.relative(args.output, cleanPath).replaceAll("\\", "/"),
          mutant_workbook: path.relative(args.output, mutantPath).replaceAll("\\", "/"),
          clean_sha256: cleanHash,
          mutant_sha256: mutantHash,
          source_cell: `Model!${mutation.cell}`,
          correct_formula: spec.formulas[mutation.cell],
          mutated_formula: mutation.formula,
          mutation_type: mutation.type,
          expected_depth: mutation.expectedDepth,
          sink_cell: `Model!${spec.sink}`,
          generator: "scripts/build_benchmarks.mjs",
          generator_version: "0.1.0",
        });
      }
    }
  }

  const manifest = {
    name: "PropagationBench-Synthetic",
    version: "0.1.0",
    generated_at: new Date().toISOString(),
    mode: args.mode,
    source_nature: "synthetic, generated by this research project",
    template_families: families.map(x => x.id),
    data_splits: [...new Set(families.map(x => x.split))],
    clean_workbooks: cleanRecords.length,
    mutant_instances: instances.length,
    random_seed_scheme: "2026081000 + family_index*100 + variant",
    label_isolation: {
      public_instances: "instances.jsonl",
      evaluation_labels: "evaluation_labels.jsonl",
      note: "FormulaGuard reads workbooks only; labels are consumed by validation/evaluation scripts.",
    },
    external_sources: [
      "https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/enron-error-corpus/",
      "https://spreadsheets.sai.tugraz.at/index.php/corpora-for-benchmarking/corpora-overview/",
    ],
  };
  await fs.writeFile(path.join(args.output, "dataset_manifest.json"), JSON.stringify(manifest, null, 2), "utf8");
  await fs.writeFile(path.join(args.output, "clean_manifest.json"), JSON.stringify(cleanRecords, null, 2), "utf8");
  const labelFields = ["source_cell", "correct_formula", "mutated_formula", "sink_cell"];
  const publicInstances = instances.map(row => Object.fromEntries(Object.entries(row).filter(([key]) => !labelFields.includes(key))));
  const labels = instances.map(row => ({
    instance_id: row.instance_id,
    source_cell: row.source_cell,
    correct_formula: row.correct_formula,
    mutated_formula: row.mutated_formula,
    sink_cell: row.sink_cell,
  }));
  await fs.writeFile(path.join(args.output, "instances.jsonl"), publicInstances.map(x => JSON.stringify(x)).join("\n") + "\n", "utf8");
  await fs.writeFile(path.join(args.output, "evaluation_labels.jsonl"), labels.map(x => JSON.stringify(x)).join("\n") + "\n", "utf8");
  const csvHeader = ["instance_id", "template_family", "data_split", "variant", "mutation_type", "expected_depth", "clean_workbook", "mutant_workbook"];
  const csvRows = [csvHeader.join(","), ...publicInstances.map(row => csvHeader.map(k => csvEscape(row[k])).join(","))];
  await fs.writeFile(path.join(args.output, "dataset_summary.csv"), csvRows.join("\n") + "\n", "utf8");
  console.log(JSON.stringify(manifest));
}

await main();
