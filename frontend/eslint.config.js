import js from "@eslint/js";
import i18next from "eslint-plugin-i18next";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "coverage", "src/api/schema.d.ts", "public"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { project: ["./tsconfig.app.json"], tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh, i18next },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        {
          allowConstantExport: true,
          // Context modules export their provider together with its hooks.
          allowExportNames: ["useAuth", "useApi", "useCan", "usePreferences", "initialLocale", "useWorkspace", "useRunStream"],
        },
      ],
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      // UI text comes from src/i18n (es default, en); literal JSX text is a bug.
      "i18next/no-literal-string": ["error", { mode: "jsx-text-only" }],
    },
  },
  {
    files: ["src/**/*.test.{ts,tsx}", "src/test/**"],
    rules: { "i18next/no-literal-string": "off" },
  },
  {
    files: ["vite.config.ts", "eslint.config.js", "playwright.config.ts", "e2e/**/*.ts"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.node },
    // Playwright tests that need testInfo but no fixtures take `({}, testInfo)` by design.
    rules: { "no-empty-pattern": "off" },
  },
);
