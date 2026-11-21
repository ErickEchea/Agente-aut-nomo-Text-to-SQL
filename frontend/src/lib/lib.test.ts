import { describe, expect, it } from "vitest";

import { ApiError, NetworkError } from "../api/client";
import { toCsv } from "./csv";
import { layoutSql, lineDiff } from "./diff";
import { errorMessage } from "./errors";
import { formatCell, formatCompact, formatDuration, formatNumber, formatRange, kindForColumn } from "./format";
import i18n from "../i18n";

describe("toCsv", () => {
  it("quotes, escapes, adds a BOM and neutralizes spreadsheet formulas", () => {
    const csv = toCsv(["nombre", "ingresos"], [
      ['Leche "Toni"', 10.5],
      ["=HYPERLINK(\"x\")", -3],
      ["a,b", null],
    ]);
    expect(csv.startsWith("﻿")).toBe(true);
    expect(csv).toContain('"Leche ""Toni"""');
    expect(csv).toContain(`"'=HYPERLINK(""x"")",-3`);
    expect(csv).toContain('"a,b",\r\n');
  });
});

describe("SQL diff", () => {
  it("breaks SQL into clauses", () => {
    expect(layoutSql("select a from t  where x = 1 group by a")).toBe("select a\nfrom t\nwhere x = 1\ngroup by a");
  });

  it("produces red/green lines with numbers", () => {
    const lines = lineDiff("SELECT a FROM t WHERE x = 1", "SELECT a FROM t WHERE x = 2");
    expect(lines.filter((l) => l.kind === "remove").map((l) => l.text)).toEqual(["WHERE x = 1"]);
    expect(lines.filter((l) => l.kind === "add").map((l) => l.text)).toEqual(["WHERE x = 2"]);
    expect(lines[0]).toEqual({ kind: "same", text: "SELECT a", oldNo: 1, newNo: 1 });
  });
});

describe("formatting (USD, es-EC / en-US)", () => {
  it("detects money, counts, percents and ids from column names", () => {
    expect(kindForColumn("ingresos_netos", [1.5])).toBe("money");
    expect(kindForColumn("unidades_vendidas", [3])).toBe("integer");
    expect(kindForColumn("participación", [0.2])).toBe("percent");
    expect(kindForColumn("producto_id", [7])).toBe("id");
    expect(kindForColumn("x", [1.25])).toBe("number");
  });

  it("formats USD per locale", () => {
    expect(formatNumber(299672.19, "en", "money")).toBe("$299,672.19");
    expect(formatNumber(299672.19, "es", "money")).toMatch(/299\.672,19/);
    expect(formatCompact(4_250_000, "en", "money")).toBe("$4.3M");
    expect(formatNumber(12.5, "en", "percent")).toBe("12.5%");
    expect(formatCell(null, "es", "number")).toBe("—");
  });

  it("formats durations and inclusive date ranges", () => {
    expect(formatDuration(412, "en")).toBe("412 ms");
    expect(formatDuration(20_400, "en")).toBe("20.4 s");
    expect(formatRange("2026-07-01", "2026-10-01", "en")).toBe("Jul 1, 2026 – Sep 30, 2026");
  });
});

describe("errorMessage", () => {
  const t = i18n.getFixedT("es");
  it("turns failures into actionable Spanish messages", () => {
    expect(errorMessage(new NetworkError(), t)).toContain("make up");
    expect(errorMessage(new ApiError(409, "busy"), t)).toContain("consulta en curso");
    expect(errorMessage(new ApiError(429, "slow", 12), t)).toContain("12 s");
    expect(errorMessage(new ApiError(503, "down"), t)).toContain("servidor");
  });
});
