/** RFC 4180 CSV with a UTF-8 BOM (Excel opens accents correctly) and formula-injection protection. */

const FORMULA_START = /^[=+\-@\t\r]/;

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text =
    typeof value === "string"
      ? value
      : typeof value === "number" || typeof value === "boolean" || typeof value === "bigint"
        ? String(value)
        : JSON.stringify(value);
  // A spreadsheet would evaluate text starting with = + - @ (CSV injection). Numbers stay numbers.
  if (typeof value === "string" && FORMULA_START.test(text)) text = `'${text}`;
  return /[",\r\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(columns: readonly string[], rows: readonly (readonly unknown[])[]): string {
  const lines = [columns.map(cell).join(","), ...rows.map((row) => row.map(cell).join(","))];
  return `\uFEFF${lines.join("\r\n")}\r\n`;
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}

export function downloadDataUrl(dataUrl: string, filename: string): void {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
}

export function safeFilename(text: string, extension: string): string {
  const base = text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase()
    .slice(0, 60);
  return `${base || "nexus"}.${extension}`;
}
