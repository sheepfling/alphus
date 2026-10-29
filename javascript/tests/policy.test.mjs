import assert from "node:assert/strict";
import test from "node:test";
import { ESLint } from "eslint";
import configuration from "@alphus/javascript-quality/eslint";
import prettier from "@alphus/javascript-quality/prettier";
import typescript from "@alphus/javascript-quality/tsconfig" with { type: "json" };

const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: configuration });

/**
 * Run the shared rules against an isolated source fixture.
 * @param {string} source - Synthetic source text.
 * @param {string} extension - JavaScript family suffix.
 * @returns {Promise<import("eslint").ESLint.LintResult>} The ESLint result.
 */
async function lintFixture(source, extension) {
  const [result] = await eslint.lintText(source, {
    filePath: `quality-fixture.${extension}`,
  });
  return result;
}

for (const extension of ["js", "jsx", "mjs", "cjs"]) {
  test(`${extension} accepts a documented, typed callable`, async () => {
    const source = [
      "/** @type {(value: number) => number} */",
      "const helper = (value) => value + 1;",
      "helper(1);",
      "",
    ].join("\n");
    const result = await lintFixture(source, extension);
    assert.deepEqual(result.messages, []);
  });

  test(`${extension} rejects an undocumented local callable`, async () => {
    const result = await lintFixture(
      "const helper = (value) => value + 1;\nhelper(1);\n",
      extension,
    );
    assert.ok(result.messages.some((message) => message.ruleId === "jsdoc/require-jsdoc"));
  });

  test(`${extension} rejects missing JSDoc parameter and return types`, async () => {
    const source = [
      "/** Increment a value.",
      " * @param value - Input.",
      " * @returns Incremented value.",
      " */",
      "function helper(value) { return value + 1; }",
      "helper(1);",
      "",
    ].join("\n");
    const result = await lintFixture(source, extension);
    const rules = new Set(result.messages.map((message) => message.ruleId));
    assert.ok(rules.has("jsdoc/require-param-type"));
    assert.ok(rules.has("jsdoc/require-returns-type"));
  });
}

test("CommonJS files accept CommonJS exports", async () => {
  const source = [
    "/** @type {(value: number) => number} */",
    "const helper = (value) => value + 1;",
    "module.exports = helper;",
    "",
  ].join("\n");
  const result = await lintFixture(source, "cjs");
  assert.deepEqual(result.messages, []);
});

test("JSX syntax is accepted in JSX files", async () => {
  const source = [
    "/** @type {() => object} */",
    "const Example = () => <main />;",
    "Example();",
    "",
  ].join("\n");
  const result = await lintFixture(source, "jsx");
  assert.deepEqual(result.messages, []);
});

test("named function expressions require JSDoc", async () => {
  const result = await lintFixture(
    "const helper = function increment(value) { return value + 1; };\nhelper(1);\n",
    "mjs",
  );
  assert.ok(result.messages.some((message) => message.ruleId === "jsdoc/require-jsdoc"));
});

test("unsafe debugger statements are rejected", async () => {
  const result = await lintFixture("debugger;\n", "js");
  assert.ok(result.messages.some((message) => message.ruleId === "no-debugger"));
});

test("the base profile keeps strict JavaScript checking enabled", () => {
  assert.deepEqual(typescript.compilerOptions, {
    allowJs: true,
    checkJs: true,
    strict: true,
    noEmit: true,
  });
});

test("the shared formatter has a stable width", () => {
  assert.equal(prettier.printWidth, 100);
});
