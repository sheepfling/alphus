import react from "@eslint-react/eslint-plugin";
import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import hooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

const javascriptFiles = ["**/*.{js,jsx,mjs,cjs}"];
const typescriptFiles = ["**/*.{ts,tsx,mts,cts}"];

export default defineConfig([
  {
    files: javascriptFiles,
    extends: [react.configs.recommended, hooks.configs.flat.recommended],
    languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
    rules: { "@eslint-react/rules-of-hooks": "off" },
  },
  {
    files: typescriptFiles,
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
      react.configs["recommended-typescript"],
      hooks.configs.flat.recommended,
    ],
    rules: { "@eslint-react/rules-of-hooks": "off" },
  },
]);
