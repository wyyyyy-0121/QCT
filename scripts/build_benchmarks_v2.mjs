import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function parseArgs(argv) {
  const args = { mode: "smoke", output: path.join(ROOT, "data", "propagationbench_v2_smoke") };
  for (let i = 2; i < argv.length; i += 1) {
    if (argv[i] === "--mode") args.mode = argv[++i];
    else if (argv[i] === "--output") args.output = path.resolve(argv[++i]);
    else throw new Error(`Unknown argument: ${argv[i]}`);
  }
  if (!new Set(["smoke", "topology", "sparse", "quick", "full"]).has(args.mode)) throw new Error(`Invalid mode: ${args.mode}`);
  return args;
}

const FAMILIES = [
  { id: "budget_tree", split: "development", title: "Department Budget", topology: "hierarchical_tree" },
  { id: "sales_timeline", split: "development", title: "Sales Timeline", topology: "horizontal_chain" },
  { id: "inventory_flow", split: "validation", title: "Inventory Flow", topology: "multi_sheet_cascade" },
  { id: "grade_matrix", split: "validation", title: "Course Grade Matrix", topology: "matrix_hub" },
  { id: "experiment_pipeline", split: "test", title: "Experiment Pipeline", topology: "multi_sheet_cascade" },
  { id: "energy_series", split: "test", title: "Energy Time Series", topology: "rolling_vertical" },
  { id: "schedule_chain", split: "test", title: "Project Schedule", topology: "horizontal_chain" },
  { id: "invoice_tree", split: "test", title: "Invoice Settlement", topology: "hierarchical_tree" },
  { id: "attendance_matrix", split: "test", title: "Attendance Matrix", topology: "matrix_hub" },
  { id: "fundraising_branches", split: "test", title: "Fundraising Channels", topology: "fork_join" },
];

function parseAddress(address) {
  const match = /^([A-Z]+)([1-9]\d*)$/.exec(address);
  if (!match) throw new Error(`Unsupported address: ${address}`);
  let col = 0;
  for (const ch of match[1]) col = col * 26 + ch.charCodeAt(0) - 64;
  return { row: Number(match[2]), col };
}

function colName(number) {
  let value = number;
  let result = "";
  while (value > 0) {
    value -= 1;
    result = String.fromCharCode(65 + (value % 26)) + result;
    value = Math.floor(value / 26);
  }
  return result;
}

function colNumber(text) {
  let result = 0;
  for (const ch of text) result = result * 26 + ch.charCodeAt(0) - 64;
  return result;
}

const FORMULA_REF_RE = /(?:(?:'(?:(?:'')|[^'])+'|[A-Za-z_][A-Za-z0-9_.]*)!)?\$?[A-Za-z]{1,3}\$?[1-9]\d*/g;

function translateFormula(formula, sourceAddress, targetAddress) {
  const source = parseAddress(sourceAddress);
  const target = parseAddress(targetAddress);
  const rowDelta = target.row - source.row;
  const colDelta = target.col - source.col;
  return formula.replace(FORMULA_REF_RE, token => {
    const separator = token.lastIndexOf("!");
    const sheet = separator >= 0 ? token.slice(0, separator + 1) : "";
    const address = separator >= 0 ? token.slice(separator + 1) : token;
    const match = /^(\$?)([A-Za-z]+)(\$?)([1-9]\d*)$/.exec(address);
    if (!match) return token;
    const colAbs = match[1] === "$";
    const rowAbs = match[3] === "$";
    const newCol = colNumber(match[2].toUpperCase()) + (colAbs ? 0 : colDelta);
    const newRow = Number(match[4]) + (rowAbs ? 0 : rowDelta);
    if (newCol < 1 || newRow < 1) return token;
    return `${sheet}${colAbs ? "$" : ""}${colName(newCol)}${rowAbs ? "$" : ""}${newRow}`;
  });
}

function createSpec(family, variant) {
  const familyIndex = FAMILIES.findIndex(item => item.id === family.id);
  return {
    family,
    variant,
    seed: 2026082000 + familyIndex * 100 + variant,
    sheets: new Map(),
    formulas: new Map(),
    anchors: {},
    sink: "",
  };
}

function ensureSheet(spec, sheetName) {
  if (!spec.sheets.has(sheetName)) {
    spec.sheets.set(sheetName, { values: new Map(), formulas: new Map(), maxRow: 1, maxCol: 1 });
  }
  return spec.sheets.get(sheetName);
}

function touch(record, address) {
  const parsed = parseAddress(address);
  record.maxRow = Math.max(record.maxRow, parsed.row);
  record.maxCol = Math.max(record.maxCol, parsed.col);
}

function putValue(spec, sheetName, address, value) {
  const record = ensureSheet(spec, sheetName);
  record.values.set(address, value);
  touch(record, address);
}

function putFormula(spec, sheetName, address, formula) {
  const record = ensureSheet(spec, sheetName);
  record.formulas.set(address, formula);
  spec.formulas.set(`${sheetName}!${address}`, formula);
  touch(record, address);
}

function addTitleAndHeaders(spec, sheetName, title, headers) {
  putValue(spec, sheetName, "A1", title);
  headers.forEach((header, index) => putValue(spec, sheetName, `${colName(index + 1)}4`, header));
}

function deterministicValue(spec, offset, base = 5, span = 40) {
  return base + ((spec.seed + offset * 17) % span) + (offset % 4) * 0.25;
}

function composeAnchor(anchor, options = {}) {
  const fn = options.fn ?? "SUM";
  const rangeEnd = options.rangeEnd ?? anchor.rangeEnd;
  const param = options.param ?? anchor.param;
  const direct = options.direct ?? anchor.direct;
  const tailOperator = options.tailOperator ?? "+";
  return `=${fn}(${anchor.rangeStart}:${rangeEnd})*(1+${param})${tailOperator}${direct}`;
}

function installAnchor(spec, depth, descriptor) {
  const anchor = { ...descriptor };
  anchor.correct = composeAnchor(anchor);
  spec.anchors[depth] = anchor;
  const [sheet, address] = anchor.cell.split("!");
  putFormula(spec, sheet, address, anchor.correct);
  if (spec.variant % 2 === 0) {
    for (const peerAddress of anchor.peerCells ?? []) {
      putFormula(spec, sheet, peerAddress, translateFormula(anchor.correct, address, peerAddress));
    }
  }
}

function addParams(spec) {
  addTitleAndHeaders(spec, "Params", `${spec.family.title} Parameters`, ["Parameter", "Value"]);
  putValue(spec, "Params", "A5", "Primary adjustment");
  putValue(spec, "Params", "B5", 0.06 + spec.variant * 0.002);
  putValue(spec, "Params", "A6", "Secondary adjustment");
  putValue(spec, "Params", "B6", 0.025 + spec.variant * 0.001);
}

function qualifiedAnchorFormula(anchor) {
  const [sourceSheet] = anchor.cell.split("!");
  const qualify = reference => reference.includes("!") ? reference : `${sourceSheet}!${reference}`;
  const rangeStart = qualify(anchor.rangeStart);
  const rangeEnd = anchor.rangeEnd.includes("!") ? anchor.rangeEnd : anchor.rangeEnd;
  return `=SUM(${rangeStart}:${rangeEnd})*(1+${qualify(anchor.param)})+${qualify(anchor.direct)}`;
}

function addCounterfactualChecks(spec) {
  addTitleAndHeaders(spec, "Checks", `${spec.family.title} Internal Consistency Checks`, ["Depth", "Independent recomputation", "Residual"]);
  for (const [index, depth] of ["deep", "medium", "shallow"].entries()) {
    const row = 5 + index;
    const anchor = spec.anchors[depth];
    putValue(spec, "Checks", `A${row}`, depth);
    putFormula(spec, "Checks", `B${row}`, qualifiedAnchorFormula(anchor));
    putFormula(spec, "Checks", `C${row}`, `=${anchor.cell}-B${row}`);
  }
}

function buildRollingVertical(spec) {
  addTitleAndHeaders(spec, "Series", spec.family.title, ["Period", "Input A", "Input B", "Adjusted", "Cumulative"]);
  putValue(spec, "Series", "B2", 0.07 + spec.variant * 0.002);
  putValue(spec, "Series", "B3", 0.03 + spec.variant * 0.001);
  for (let row = 5; row <= 24; row += 1) {
    putValue(spec, "Series", `A${row}`, `T${row - 4}`);
    putValue(spec, "Series", `B${row}`, deterministicValue(spec, row, 8, 35));
    putValue(spec, "Series", `C${row}`, deterministicValue(spec, row + 30, 3, 22));
    if (row <= 22) {
      putFormula(spec, "Series", `D${row}`, `=SUM(B${row}:B${row + 2})*(1+$B$2)+C${row + 2}`);
      putFormula(spec, "Series", `E${row}`, row === 5 ? `=D${row}*(1+$B$3)` : `=E${row - 1}+D${row}`);
    }
  }
  installAnchor(spec, "deep", {
    cell: "Series!D5", rangeStart: "B5", rangeEnd: "B7", rangeEndPrev: "B6",
    param: "$B$2", paramWrong: "B3", direct: "C7", directPrev: "C6", directNext: "C8",
    peerCells: ["D6", "D7"],
  });
  installAnchor(spec, "medium", {
    cell: "Series!D18", rangeStart: "B18", rangeEnd: "B20", rangeEndPrev: "B19",
    param: "$B$2", paramWrong: "B3", direct: "C20", directPrev: "C19", directNext: "C21",
    peerCells: ["D17", "D19"],
  });
  installAnchor(spec, "shallow", {
    cell: "Series!D21", rangeStart: "B21", rangeEnd: "B23", rangeEndPrev: "B22",
    param: "$B$2", paramWrong: "B3", direct: "C23", directPrev: "C22", directNext: "C24",
    peerCells: ["D20", "D22"],
  });
  spec.sink = "Series!E22";
}

function buildHorizontalChain(spec) {
  addTitleAndHeaders(spec, "Timeline", spec.family.title, ["Metric", "Parameter"]);
  putValue(spec, "Timeline", "B2", 0.055 + spec.variant * 0.002);
  putValue(spec, "Timeline", "B3", 0.02 + spec.variant * 0.001);
  for (let col = 3; col <= 18; col += 1) {
    const letter = colName(col);
    putValue(spec, "Timeline", `${letter}4`, `P${col - 2}`);
    for (let row = 9; row <= 14; row += 1) putValue(spec, "Timeline", `${letter}${row}`, deterministicValue(spec, col * 20 + row, 4, 30));
    if (![3, 14, 17, 18].includes(col)) {
      const previous = colName(col - 1);
      putFormula(spec, "Timeline", `${letter}5`, col === 3 ? `=SUM(${letter}7:${letter}9)` : `=${previous}5+SUM(${letter}7:${letter}9)`);
    }
  }
  installAnchor(spec, "deep", {
    cell: "Timeline!C5", rangeStart: "C9", rangeEnd: "C11", rangeEndPrev: "C10",
    param: "$B$2", paramWrong: "B3", direct: "C12", directPrev: "C11", directNext: "C13",
    peerCells: ["C6", "C7"],
  });
  installAnchor(spec, "medium", {
    cell: "Timeline!N5", rangeStart: "N9", rangeEnd: "N11", rangeEndPrev: "N10",
    param: "$B$2", paramWrong: "B3", direct: "N12", directPrev: "N11", directNext: "N13",
    peerCells: ["N6", "N7"],
  });
  installAnchor(spec, "shallow", {
    cell: "Timeline!Q5", rangeStart: "Q9", rangeEnd: "Q11", rangeEndPrev: "Q10",
    param: "$B$2", paramWrong: "B3", direct: "Q12", directPrev: "Q11", directNext: "Q13",
    peerCells: ["Q6", "Q7"],
  });
  putFormula(spec, "Timeline", "R5", "=M5+P5+Q5");
  putFormula(spec, "Timeline", "R6", "=R5*(1+$B$3)");
  spec.sink = "Timeline!R6";
}

function buildMultiSheetCascade(spec) {
  addParams(spec);
  addTitleAndHeaders(spec, "Detail", `${spec.family.title} Detail`, ["Item", "Input A", "Input B", "Running result", "Adjusted result"]);
  for (let row = 5; row <= 16; row += 1) {
    putValue(spec, "Detail", `A${row}`, `Item ${row - 4}`);
    putValue(spec, "Detail", `B${row}`, deterministicValue(spec, row, 6, 32));
    putValue(spec, "Detail", `C${row}`, deterministicValue(spec, row + 40, 3, 24));
    if (row !== 5) putFormula(spec, "Detail", `D${row}`, `=D${row - 1}+B${row}*C${row}`);
    putFormula(spec, "Detail", `E${row}`, `=D${row}*(1+Params!$B$6)`);
  }
  installAnchor(spec, "deep", {
    cell: "Detail!D5", rangeStart: "B5", rangeEnd: "B7", rangeEndPrev: "B6",
    param: "Params!$B$5", paramWrong: "Params!B6", direct: "C7", directPrev: "C6", directNext: "C8",
    peerCells: ["F5", "G5"],
  });

  addTitleAndHeaders(spec, "Summary", `${spec.family.title} Summary`, ["Stage", "Value"]);
  installAnchor(spec, "medium", {
    cell: "Summary!B5", rangeStart: "Detail!D14", rangeEnd: "D16", rangeEndPrev: "D15",
    param: "Params!$B$5", paramWrong: "Params!B6", direct: "Detail!C14", directPrev: "Detail!C13", directNext: "Detail!C15",
    peerCells: ["C5", "D5"],
  });
  putFormula(spec, "Summary", "B6", "=B5+Detail!D16");
  putFormula(spec, "Summary", "B7", "=B6*(1+Params!$B$6)");

  addTitleAndHeaders(spec, "Dashboard", `${spec.family.title} Dashboard`, ["Indicator", "Value"]);
  installAnchor(spec, "shallow", {
    cell: "Dashboard!B5", rangeStart: "Detail!C5", rangeEnd: "C7", rangeEndPrev: "C6",
    param: "Params!$B$5", paramWrong: "Params!B6", direct: "Detail!B7", directPrev: "Detail!B6", directNext: "Detail!B8",
    peerCells: ["C5", "D5"],
  });
  putFormula(spec, "Dashboard", "B6", "=Summary!B7+B5");
  putFormula(spec, "Dashboard", "B7", "=B6*(1+Params!$B$6)");
  spec.sink = "Dashboard!B7";
}

function buildMatrixHub(spec) {
  addTitleAndHeaders(spec, "Matrix", spec.family.title, ["Entity", "M1", "M2", "M3", "M4", "M5", "Row score", "Normalized"]);
  putValue(spec, "Matrix", "B2", 0.065 + spec.variant * 0.002);
  putValue(spec, "Matrix", "B3", 0.025 + spec.variant * 0.001);
  for (let row = 5; row <= 10; row += 1) {
    putValue(spec, "Matrix", `A${row}`, `E${row - 4}`);
    for (let col = 2; col <= 6; col += 1) putValue(spec, "Matrix", `${colName(col)}${row}`, deterministicValue(spec, row * 20 + col, 2, 18));
    if (![5, 9, 10].includes(row)) putFormula(spec, "Matrix", `G${row}`, `=SUM(B${row}:F${row})*(1+$B$2)`);
    putFormula(spec, "Matrix", `H${row}`, `=G${row}/(1+$B$3)`);
  }
  installAnchor(spec, "deep", {
    cell: "Matrix!G5", rangeStart: "B5", rangeEnd: "F5", rangeEndPrev: "E5",
    param: "$B$2", paramWrong: "B3", direct: "D5", directPrev: "C5", directNext: "E5",
    peerCells: ["G6", "G7"],
  });
  installAnchor(spec, "medium", {
    cell: "Matrix!G9", rangeStart: "B9", rangeEnd: "F9", rangeEndPrev: "E9",
    param: "$B$2", paramWrong: "B3", direct: "D9", directPrev: "C9", directNext: "E9",
    peerCells: ["G8", "G10"],
  });
  installAnchor(spec, "shallow", {
    cell: "Matrix!G10", rangeStart: "B10", rangeEnd: "F10", rangeEndPrev: "E10",
    param: "$B$2", paramWrong: "B3", direct: "D10", directPrev: "C10", directNext: "E10",
    peerCells: ["G8", "G9"],
  });
  for (let col = 2; col <= 6; col += 1) {
    const letter = colName(col);
    putFormula(spec, "Matrix", `${letter}12`, `=AVERAGE(${letter}5:${letter}10)`);
  }
  addTitleAndHeaders(spec, "Summary", `${spec.family.title} Hub`, ["Step", "Value"]);
  putFormula(spec, "Summary", "B5", "=Matrix!G5+Matrix!G6");
  putFormula(spec, "Summary", "B6", "=B5+Matrix!G7");
  putFormula(spec, "Summary", "B7", "=B6+Matrix!G8");
  putFormula(spec, "Summary", "B8", "=B7+Matrix!G9");
  putFormula(spec, "Summary", "B9", "=B8+Matrix!G10");
  putFormula(spec, "Summary", "B10", "=B9*(1+Matrix!$B$3)");
  spec.sink = "Summary!B10";
}

function buildHierarchicalTree(spec) {
  addParams(spec);
  addTitleAndHeaders(spec, "Detail", `${spec.family.title} Lines`, ["Line", "Quantity", "Rate", "Amount"]);
  for (let row = 5; row <= 14; row += 1) {
    putValue(spec, "Detail", `A${row}`, `Line ${row - 4}`);
    putValue(spec, "Detail", `B${row}`, deterministicValue(spec, row, 2, 20));
    putValue(spec, "Detail", `C${row}`, deterministicValue(spec, row + 50, 8, 35));
    if (row !== 5) putFormula(spec, "Detail", `D${row}`, `=B${row}*C${row}`);
  }
  installAnchor(spec, "deep", {
    cell: "Detail!D5", rangeStart: "B5", rangeEnd: "B7", rangeEndPrev: "B6",
    param: "Params!$B$5", paramWrong: "Params!B6", direct: "C7", directPrev: "C6", directNext: "C8",
    peerCells: ["E5", "F5"],
  });
  addTitleAndHeaders(spec, "Section", `${spec.family.title} Sections`, ["Section", "Subtotal"]);
  putFormula(spec, "Section", "B5", "=SUM(Detail!D5:D7)");
  putFormula(spec, "Section", "B6", "=B5+SUM(Detail!D8:D10)");
  putFormula(spec, "Section", "B7", "=B6+SUM(Detail!D11:D14)");
  putFormula(spec, "Section", "B8", "=B7*(1+Params!$B$6)");

  addTitleAndHeaders(spec, "Report", `${spec.family.title} Report`, ["Stage", "Value"]);
  installAnchor(spec, "medium", {
    cell: "Report!B5", rangeStart: "Detail!C12", rangeEnd: "C14", rangeEndPrev: "C13",
    param: "Params!$B$5", paramWrong: "Params!B6", direct: "Section!B7", directPrev: "Section!B6", directNext: "Section!B8",
    peerCells: ["C5", "D5"],
  });
  putFormula(spec, "Report", "B6", "=B5*(1+Params!$B$6)");
  installAnchor(spec, "shallow", {
    cell: "Report!B7", rangeStart: "Detail!C5", rangeEnd: "C7", rangeEndPrev: "C6",
    param: "Params!$B$5", paramWrong: "Params!B6", direct: "Detail!B7", directPrev: "Detail!B6", directNext: "Detail!B8",
    peerCells: ["C7", "D7"],
  });
  putFormula(spec, "Report", "B8", "=B6+B7");
  putFormula(spec, "Report", "B9", "=B8*(1+Params!$B$6)");
  spec.sink = "Report!B9";
}

function buildForkJoin(spec) {
  addParams(spec);
  const branches = [
    { sheet: "North", length: 10, depth: "deep" },
    { sheet: "South", length: 7, depth: "medium" },
    { sheet: "Central", length: 5, depth: "shallow" },
  ];
  for (const [branchIndex, branch] of branches.entries()) {
    addTitleAndHeaders(spec, branch.sheet, `${spec.family.title} ${branch.sheet}`, ["Source", "Input A", "Input B", "Branch total"]);
    const dataEnd = Math.max(8, branch.length);
    for (let row = 5; row <= dataEnd; row += 1) {
      putValue(spec, branch.sheet, `A${row}`, `${branch.sheet}-${row - 4}`);
      putValue(spec, branch.sheet, `B${row}`, deterministicValue(spec, branchIndex * 50 + row, 3, 28));
      putValue(spec, branch.sheet, `C${row}`, deterministicValue(spec, branchIndex * 50 + row + 20, 5, 22));
      if (row > 5 && row <= branch.length) putFormula(spec, branch.sheet, `D${row}`, `=D${row - 1}+B${row}*C${row}`);
    }
    installAnchor(spec, branch.depth, {
      cell: `${branch.sheet}!D5`, rangeStart: "B5", rangeEnd: "B7", rangeEndPrev: "B6",
      param: "Params!$B$5", paramWrong: "Params!B6", direct: "C7", directPrev: "C6", directNext: "C8",
      peerCells: ["E5", "F5"],
    });
  }
  addTitleAndHeaders(spec, "Dashboard", `${spec.family.title} Dashboard`, ["Branch", "Value"]);
  putFormula(spec, "Dashboard", "B5", "=North!D10");
  putFormula(spec, "Dashboard", "B6", "=South!D7");
  putFormula(spec, "Dashboard", "B7", "=Central!D5");
  putFormula(spec, "Dashboard", "B8", "=SUM(B5:B7)*(1+Params!$B$6)");
  spec.sink = "Dashboard!B8";
}

function workbookSpec(family, variant) {
  const spec = createSpec(family, variant);
  const builders = {
    rolling_vertical: buildRollingVertical,
    horizontal_chain: buildHorizontalChain,
    multi_sheet_cascade: buildMultiSheetCascade,
    matrix_hub: buildMatrixHub,
    hierarchical_tree: buildHierarchicalTree,
    fork_join: buildForkJoin,
  };
  builders[family.topology](spec);
  if (!spec.sink || !spec.anchors.deep || !spec.anchors.medium || !spec.anchors.shallow) {
    throw new Error(`Incomplete topology specification: ${family.id}`);
  }
  addCounterfactualChecks(spec);
  return spec;
}

const MUTATION_ORDER = [
  ["M1_reference_shift", "deep"], ["M2_range_boundary", "medium"], ["M3_operator", "shallow"],
  ["M4_function", "deep"], ["M5_absolute_reference", "medium"], ["M6_copy_offset", "shallow"],
  ["M1_reference_shift", "medium"], ["M1_reference_shift", "shallow"],
  ["M2_range_boundary", "deep"], ["M2_range_boundary", "shallow"],
  ["M3_operator", "deep"], ["M3_operator", "medium"],
  ["M4_function", "medium"], ["M4_function", "shallow"],
  ["M5_absolute_reference", "deep"], ["M5_absolute_reference", "shallow"],
  ["M6_copy_offset", "deep"], ["M6_copy_offset", "medium"],
];

function mutatedFormula(anchor, mutationType) {
  if (mutationType === "M1_reference_shift") return composeAnchor(anchor, { direct: anchor.directPrev });
  if (mutationType === "M2_range_boundary") return composeAnchor(anchor, { rangeEnd: anchor.rangeEndPrev });
  if (mutationType === "M3_operator") return composeAnchor(anchor, { tailOperator: "-" });
  if (mutationType === "M4_function") return composeAnchor(anchor, { fn: "AVERAGE" });
  if (mutationType === "M5_absolute_reference") return composeAnchor(anchor, { param: anchor.paramWrong });
  if (mutationType === "M6_copy_offset") return composeAnchor(anchor, { direct: anchor.directNext });
  throw new Error(`Unknown mutation type: ${mutationType}`);
}

function mutationCatalog(spec) {
  return MUTATION_ORDER.map(([type, depth], index) => {
    const anchor = spec.anchors[depth];
    const formula = mutatedFormula(anchor, type);
    if (formula === anchor.correct) throw new Error(`No-op mutation for ${spec.family.id} ${type} ${depth}`);
    return {
      id: `${type.slice(0, 2)}_${depth}_${String(index + 1).padStart(2, "0")}`,
      type,
      expectedDepth: depth,
      cell: anchor.cell,
      formula,
    };
  });
}

function styleSheet(sheet, record) {
  const lastCol = colName(Math.max(8, record.maxCol));
  const end = `${lastCol}${Math.max(6, record.maxRow)}`;
  sheet.showGridLines = false;
  sheet.freezePanes.freezeRows(4);
  sheet.getRange(`A1:${lastCol}1`).merge();
  sheet.getRange(`A1:${lastCol}1`).format = {
    fill: "#17365D", font: { bold: true, color: "#FFFFFF", size: 15 },
    horizontalAlignment: "center", verticalAlignment: "center", rowHeight: 27,
  };
  sheet.getRange(`A4:${lastCol}4`).format = {
    fill: "#2E75B6", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center",
  };
  sheet.getRange(`A5:${end}`).format.borders = { preset: "inside", style: "thin", color: "#D7DEE8" };
  sheet.getRange(`A1:${end}`).format.font = { name: "Arial", size: 10 };
  sheet.getRange(`A1:${lastCol}1`).format.font = { name: "Arial", size: 15, bold: true, color: "#FFFFFF" };
  sheet.getRange("A:A").format.columnWidth = 18;
  for (let col = 2; col <= record.maxCol; col += 1) sheet.getRange(`${colName(col)}:${colName(col)}`).format.columnWidth = 14;
}

function buildWorkbook(spec, mutation = null) {
  const workbook = Workbook.create();
  for (const [sheetName, record] of spec.sheets.entries()) {
    const sheet = workbook.worksheets.add(sheetName);
    for (const [address, value] of record.values.entries()) sheet.getRange(address).values = [[value]];
    for (const [address, formula] of record.formulas.entries()) {
      const key = `${sheetName}!${address}`;
      sheet.getRange(address).formulas = [[mutation?.cell === key ? mutation.formula : formula]];
    }
    styleSheet(sheet, record);
  }
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
  await fs.rm(`${filePath}.inspect.ndjson`, { force: true });
}

async function removeDiagnosticSidecars(directory) {
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    const itemPath = path.join(directory, entry.name);
    if (entry.isDirectory()) await removeDiagnosticSidecars(itemPath);
    else if (entry.name.endsWith(".xlsx.inspect.ndjson")) await fs.rm(itemPath, { force: true });
  }
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
    ? FAMILIES.filter(item => item.split === "development")
    : args.mode === "topology" || args.mode === "sparse" || args.mode === "full"
      ? FAMILIES.filter(item => item.split === "test")
      : args.mode === "quick"
      ? FAMILIES.filter(item => item.split !== "test")
      : [];
  const variantValues = args.mode === "full"
    ? Array.from({ length: 8 }, (_, index) => index)
    : args.mode === "quick"
      ? [0, 1]
      : args.mode === "sparse"
        ? [1]
        : [0];
  const mutationCount = args.mode === "full" ? 18 : 6;
  const instances = [];
  const cleanRecords = [];
  let previewWritten = false;

  for (const family of families) {
    for (const variant of variantValues) {
      const spec = workbookSpec(family, variant);
      const cleanId = `${family.id}_v${variant}`;
      const cleanPath = path.join(cleanDir, `${cleanId}.xlsx`);
      const cleanWorkbook = buildWorkbook(spec);
      await exportWorkbook(cleanWorkbook, cleanPath);
      const cleanHash = await sha256(cleanPath);
      cleanRecords.push({
        cleanId, family: family.id, topology_id: family.topology, data_split: family.split, variant,
        sheet_count: spec.sheets.size, formula_count: spec.formulas.size,
        path: path.relative(args.output, cleanPath).replaceAll("\\", "/"), sha256: cleanHash,
      });

      if (!previewWritten) {
        const inspection = await cleanWorkbook.inspect({ kind: "workbook,sheet,formula", maxChars: 12000, tableMaxRows: 35, tableMaxCols: 12 });
        await fs.writeFile(path.join(previewDir, "verification_first.ndjson"), inspection.ndjson, "utf8");
        const errors = await cleanWorkbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
        await fs.writeFile(path.join(previewDir, "formula_error_scan.ndjson"), errors.ndjson, "utf8");
        const firstSheet = spec.sheets.keys().next().value;
        const rendered = await cleanWorkbook.render({ sheetName: firstSheet, autoCrop: "all", scale: 1.2, format: "png" });
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
          topology_id: family.topology,
          data_split: family.split,
          variant,
          seed: spec.seed,
          clean_workbook: path.relative(args.output, cleanPath).replaceAll("\\", "/"),
          mutant_workbook: path.relative(args.output, mutantPath).replaceAll("\\", "/"),
          clean_sha256: cleanHash,
          mutant_sha256: mutantHash,
          source_cell: mutation.cell,
          correct_formula: spec.formulas.get(mutation.cell),
          mutated_formula: mutation.formula,
          mutation_type: mutation.type,
          expected_depth: mutation.expectedDepth,
          sink_cell: spec.sink,
          generator: "scripts/build_benchmarks_v2.mjs",
          generator_version: "0.2.0",
        });
      }
    }
  }

  const manifest = {
    name: "PropagationBench-V2-Synthetic",
    version: "0.2.0",
    generated_at: new Date().toISOString(),
    mode: args.mode,
    source_nature: "synthetic, structurally diverse, generated by this research project",
    template_families: families.map(item => item.id),
    topology_profiles: families.map(item => ({ family: item.id, topology_id: item.topology })),
    data_splits: [...new Set(families.map(item => item.split))],
    clean_workbooks: cleanRecords.length,
    mutant_instances: instances.length,
    random_seed_scheme: "2026082000 + family_index*100 + variant",
    design_note: "Test families use six distinct dependency layouts: cascade, rolling sequence, horizontal chain, hierarchy, matrix hub, and fork-join.",
    label_isolation: {
      public_instances: "instances.jsonl",
      evaluation_labels: "evaluation_labels.jsonl",
      note: "FormulaGuard reads workbooks only; labels are consumed after oracle-free ranking.",
    },
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
  await fs.writeFile(path.join(args.output, "instances.jsonl"), publicInstances.map(row => JSON.stringify(row)).join("\n") + "\n", "utf8");
  await fs.writeFile(path.join(args.output, "evaluation_labels.jsonl"), labels.map(row => JSON.stringify(row)).join("\n") + "\n", "utf8");
  const csvHeader = ["instance_id", "template_family", "topology_id", "data_split", "variant", "mutation_type", "expected_depth", "clean_workbook", "mutant_workbook"];
  const csvRows = [csvHeader.join(","), ...publicInstances.map(row => csvHeader.map(key => csvEscape(row[key])).join(","))];
  await fs.writeFile(path.join(args.output, "dataset_summary.csv"), csvRows.join("\n") + "\n", "utf8");
  await removeDiagnosticSidecars(args.output);
  console.log(JSON.stringify(manifest));
}

await main();
