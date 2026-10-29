import assert from "node:assert/strict";
import test from "node:test";
import { ESLint } from "eslint";
import angular from "@alphus/javascript-quality/eslint/angular";
import javascript from "@alphus/javascript-quality/eslint";
import react from "@alphus/javascript-quality/eslint/react";

/**
 * Lint one synthetic consumer file with a selected flat configuration.
 * @param {import("eslint").Linter.Config[]} configuration - Shared profile composition.
 * @param {string} filePath - Synthetic consumer file name.
 * @param {string} source - Source to inspect.
 * @returns {Promise<import("eslint").ESLint.LintResult>} Lint result.
 */
async function lintFixture(configuration, filePath, source) {
  const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: configuration });
  const [result] = await eslint.lintText(source, { filePath });
  return result;
}

test("React rules inspect JSX without changing the general JavaScript profile", async () => {
  const source = "const List = () => <ul>{[1].map((item) => <li>{item}</li>)}</ul>;\nList();\n";
  const plain = await lintFixture(javascript, "fixture.jsx", source);
  const enhanced = await lintFixture([...javascript, ...react], "fixture.jsx", source);
  assert.ok(!plain.messages.some((message) => message.ruleId === "@eslint-react/no-missing-key"));
  assert.ok(enhanced.messages.some((message) => message.ruleId === "@eslint-react/no-missing-key"));
});

test("React reports conditional Hooks once through the official plugin", async () => {
  const source = [
    'import { useState } from "react";',
    "function Widget({ visible }) {",
    "  if (visible) useState(0);",
    "  return <div />;",
    "}",
    "Widget({ visible: true });",
  ].join("\n");
  const result = await lintFixture([...javascript, ...react], "fixture.jsx", source);
  const hookFindings = result.messages.filter((message) =>
    message.ruleId?.endsWith("rules-of-hooks"),
  );
  assert.deepEqual(
    hookFindings.map((message) => message.ruleId),
    ["react-hooks/rules-of-hooks"],
  );
});

test("React profile parses TSX and reports framework rules", async () => {
  const source = [
    "export function Items({ values }: { values: string[] }) {",
    "  return <ul>{values.map((value) => <li>{value}</li>)}</ul>;",
    "}",
  ].join("\n");
  const result = await lintFixture(react, "fixture.tsx", source);
  assert.ok(result.messages.some((message) => message.ruleId === "@eslint-react/no-missing-key"));
  assert.ok(!result.messages.some((message) => message.fatal));
});

test("Angular profile checks decorators and inline templates", async () => {
  const source = [
    'import { Component } from "@angular/core";',
    '@Component({selector: "app-demo", standalone: false, inputs: ["value"], template: "<img src=\\"x\\">"})',
    "export class Demo {}",
  ].join("\n");
  const result = await lintFixture(angular, "fixture.ts", source);
  const rules = new Set(result.messages.map((message) => message.ruleId));
  assert.ok(rules.has("@angular-eslint/no-inputs-metadata-property"));
  assert.ok(rules.has("@angular-eslint/template/alt-text"));
});

test("Angular profile checks external HTML templates", async () => {
  const result = await lintFixture(angular, "fixture.html", '<img src="photo.png">\n');
  assert.ok(
    result.messages.some((message) => message.ruleId === "@angular-eslint/template/alt-text"),
  );
});
