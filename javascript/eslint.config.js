import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import jsdoc from "eslint-plugin-jsdoc";
import globals from "globals";

const sourceFiles = ["**/*.{js,jsx,mjs,cjs}"];

export default defineConfig([
  {
    ignores: ["**/node_modules/**", "**/vendor/**", "**/dist/**", "**/build/**", "**/coverage/**"],
  },
  {
    files: sourceFiles,
    plugins: { jsdoc },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      ...js.configs.recommended.rules,
      "constructor-super": "error",
      "no-debugger": "error",
      "no-unsafe-finally": "error",
      "no-unreachable": "error",
      "jsdoc/check-param-names": "error",
      "jsdoc/check-tag-names": "error",
      "jsdoc/valid-types": "error",
      "jsdoc/require-jsdoc": [
        "error",
        {
          publicOnly: false,
          contexts: [
            "VariableDeclarator > ArrowFunctionExpression",
            "VariableDeclarator > FunctionExpression",
          ],
        },
      ],
      "jsdoc/require-param": "error",
      "jsdoc/require-param-description": "error",
      "jsdoc/require-param-type": "error",
      "jsdoc/require-returns": "error",
      "jsdoc/require-returns-description": "error",
      "jsdoc/require-returns-type": "error",
    },
  },
  {
    files: ["**/*.cjs"],
    languageOptions: { sourceType: "commonjs" },
  },
]);
