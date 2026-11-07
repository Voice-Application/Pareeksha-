/** Line diff by longest common subsequence. No dependency: prompts are at most a few thousand lines. */

export type DiffLine = { kind: "same" | "add" | "del"; text: string; /** 1-based line in the old text */ a?: number; /** 1-based line in the new text */ b?: number };
export type DiffRow = { type: "line"; line: DiffLine } | { type: "skip"; lines: DiffLine[] };
export type DiffResult = { tooLarge: false; lines: DiffLine[] } | { tooLarge: true; message: string };

/** Upper bound on LCS table cells (4 bytes each, so 16 MB). Larger changed regions are not diffed. */
export const MAX_DIFF_CELLS = 4_000_000;

const split = (s: string) => (s === "" ? [] : s.replace(/\r\n?/g, "\n").split("\n"));

export function lineDiff(before: string, after: string): DiffResult {
  const a = split(before);
  const b = split(after);
  // Trim the shared head and tail so the quadratic table only covers the changed middle.
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }
  const n = endA - start;
  const m = endB - start;
  if ((n + 1) * (m + 1) > MAX_DIFF_CELLS)
    return { tooLarge: true, message: `Too large to diff here: the changed part is ${n.toLocaleString("en-IN")} lines before and ${m.toLocaleString("en-IN")} lines after.` };
  // lcs[i][j] = LCS length of a[start+i..endA) and b[start+j..endB), row-major in one typed array.
  const w = m + 1;
  const lcs = new Uint32Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i * w + j] = a[start + i] === b[start + j] ? lcs[(i + 1) * w + j + 1] + 1 : Math.max(lcs[(i + 1) * w + j], lcs[i * w + j + 1]);
    }
  }

  const out: DiffLine[] = [];
  for (let k = 0; k < start; k++) out.push({ kind: "same", text: a[k], a: k + 1, b: k + 1 });
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && a[start + i] === b[start + j]) {
      out.push({ kind: "same", text: a[start + i], a: start + i + 1, b: start + j + 1 });
      i++;
      j++;
    } else if (j < m && (i === n || lcs[i * w + j + 1] >= lcs[(i + 1) * w + j])) {
      out.push({ kind: "add", text: b[start + j], b: start + j + 1 });
      j++;
    } else {
      out.push({ kind: "del", text: a[start + i], a: start + i + 1 });
      i++;
    }
  }
  for (let k = 0; k < a.length - endA; k++) out.push({ kind: "same", text: a[endA + k], a: endA + k + 1, b: endB + k + 1 });
  // Within a changed block, show removals before additions.
  return { tooLarge: false, lines: reorder(out) };
}

function reorder(lines: DiffLine[]): DiffLine[] {
  const out: DiffLine[] = [];
  let dels: DiffLine[] = [];
  let adds: DiffLine[] = [];
  const flush = () => {
    out.push(...dels, ...adds);
    dels = [];
    adds = [];
  };
  for (const l of lines) {
    if (l.kind === "del") dels.push(l);
    else if (l.kind === "add") adds.push(l);
    else {
      flush();
      out.push(l);
    }
  }
  flush();
  return out;
}

/** Keep `context` unchanged lines around each change; fold longer unchanged runs into one skip row. */
export function collapse(lines: DiffLine[], context = 2): DiffRow[] {
  const keep = new Array<boolean>(lines.length).fill(false);
  lines.forEach((l, i) => {
    if (l.kind === "same") return;
    for (let k = Math.max(0, i - context); k <= Math.min(lines.length - 1, i + context); k++) keep[k] = true;
  });
  const rows: DiffRow[] = [];
  let run: DiffLine[] = [];
  const flush = () => {
    if (run.length) rows.push({ type: "skip", lines: run });
    run = [];
  };
  lines.forEach((l, i) => {
    if (keep[i]) {
      flush();
      rows.push({ type: "line", line: l });
    } else run.push(l);
  });
  flush();
  return rows;
}

export const hasChanges = (lines: DiffLine[]) => lines.some((l) => l.kind !== "same");
