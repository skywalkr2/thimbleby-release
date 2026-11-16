// A small, standard rule set for the web code: ESLint's recommended rules, the TypeScript recommended rules, the two rules
// of hooks, and two type-aware rules that catch a promise nobody waits for. A rule is turned off here with its reason,
// never on one line without one.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";
import { BARE_INVALIDATE_EXCEPTIONS } from "./eslint.bare-invalidate-exceptions.js";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "src/api/schema.d.ts", "visual/**", "e2e/**", "e2e-install/**", "stylelint/**", "playwright*.ts", "src/lib/lint-fixtures/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      globals: { ...globals.browser },
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      // A leading underscore names a value taken out only to leave it behind (`({ [key]: _gone, ...rest }) => rest`).
      "@typescript-eslint/no-unused-vars": ["error", { varsIgnorePattern: "^_", argsIgnorePattern: "^_", ignoreRestSiblings: true }],
      // The tests write non-breaking and narrow spaces on purpose, inside strings and patterns, to check what the screen
      // prints; a stray one in code is still caught.
      "no-irregular-whitespace": ["error", { skipStrings: true, skipTemplates: true, skipRegExps: true, skipComments: true }],
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": ["error", { checksVoidReturn: { attributes: false } }],
    },
  },
  {
    // A write names the screens it changed (`useWrite`); a refresh of everything belongs to the stream's reconnect only. Tests
    // drive the stream by hand and are exempt.
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/lib/live.ts", "src/lib/write.ts", "src/**/*.test.{ts,tsx}", ...BARE_INVALIDATE_EXCEPTIONS],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.property.name='invalidateQueries'][arguments.length=0]",
          message: "Name the query families the write changed (useWrite, touches); a bare invalidateQueries() reads every screen again.",
        },
      ],
    },
  },
);
