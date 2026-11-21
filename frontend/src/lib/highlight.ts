/**
 * SQL highlighting with Shiki's fine-grained core: only the SQL grammar and the JavaScript regex
 * engine (no WASM, so the strict CSP needs no 'wasm-unsafe-eval'). Token colors are CSS variables
 * mapped to the design tokens, so highlighting follows the theme switch without re-rendering.
 */
import type { HighlighterCore, ThemedToken } from "shiki/core";

let highlighter: Promise<HighlighterCore> | null = null;

const THEME = "nexus-tokens";

function load(): Promise<HighlighterCore> {
  highlighter ??= (async () => {
    const [{ createHighlighterCore, createCssVariablesTheme }, { createJavaScriptRegexEngine }, sql] =
      await Promise.all([
        import("shiki/core"),
        import("shiki/engine/javascript"),
        import("shiki/langs/sql.mjs"),
      ]);
    return createHighlighterCore({
      themes: [createCssVariablesTheme({ name: THEME, variablePrefix: "--shiki-", fontStyle: true })],
      langs: [sql.default],
      engine: createJavaScriptRegexEngine(),
    });
  })();
  return highlighter;
}

export async function tokenizeSql(code: string): Promise<ThemedToken[][]> {
  const instance = await load();
  return instance.codeToTokensBase(code, { lang: "sql", theme: THEME });
}
