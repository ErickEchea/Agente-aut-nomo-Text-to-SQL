import { diffLines } from "diff";

export type DiffKind = "add" | "remove" | "same";

export interface DiffLine {
  kind: DiffKind;
  text: string;
  /** Line number in the old (remove/same) or new (add/same) text, 1-based. */
  oldNo: number | null;
  newNo: number | null;
}

/** SQL often arrives as one long line: break before major clauses so a diff is readable. */
export function layoutSql(sql: string): string {
  return sql
    .replace(/\s+/g, " ")
    .replace(
      /\s+(?=\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|OFFSET|UNION ALL|UNION|WITH|(?:LEFT |RIGHT |FULL |INNER |CROSS )?JOIN|AND|OR)\b)/gi,
      "\n",
    )
    .trim();
}

export function lineDiff(before: string, after: string): DiffLine[] {
  const lines: DiffLine[] = [];
  let oldNo = 1;
  let newNo = 1;
  for (const part of diffLines(layoutSql(before), layoutSql(after))) {
    const texts = part.value.replace(/\n$/, "").split("\n");
    for (const text of texts) {
      if (part.added) lines.push({ kind: "add", text, oldNo: null, newNo: newNo++ });
      else if (part.removed) lines.push({ kind: "remove", text, oldNo: oldNo++, newNo: null });
      else lines.push({ kind: "same", text, oldNo: oldNo++, newNo: newNo++ });
    }
  }
  return lines;
}
