import assert from "node:assert/strict";
import test from "node:test";
import { HtmlValidate } from "html-validate";
import prettier from "prettier";
import stylelint from "stylelint";
import htmlConfiguration from "@alphus/javascript-quality/html-validate";
import prettierConfiguration from "@alphus/javascript-quality/prettier";
import cssConfiguration from "@alphus/javascript-quality/stylelint";

test("HTML profile accepts a complete document", async () => {
  const validator = new HtmlValidate(htmlConfiguration);
  const source =
    '<!doctype html><html lang="en"><head><title>Example</title></head><body><p>Hello</p></body></html>';
  const report = await validator.validateString(source, "fixture.html");
  assert.equal(report.valid, true);
});

test("HTML profile reports missing image alternatives", async () => {
  const validator = new HtmlValidate(htmlConfiguration);
  const source =
    '<!doctype html><html lang="en"><head><title>Example</title></head><body><img src="x"></body></html>';
  const report = await validator.validateString(source, "fixture.html");
  assert.ok(
    report.results.some((result) =>
      result.messages.some((message) => message.ruleId === "wcag/h37"),
    ),
  );
});

test("CSS profile accepts valid CSS and reports invalid values", async () => {
  const valid = await stylelint.lint({
    code: "p { color: red; }",
    codeFilename: "valid.css",
    config: cssConfiguration,
  });
  const invalid = await stylelint.lint({
    code: "p { color: #ggg; }",
    codeFilename: "invalid.css",
    config: cssConfiguration,
  });
  assert.equal(valid.errored, false);
  assert.ok(
    invalid.results.some((result) =>
      result.warnings.some((warning) => warning.rule === "declaration-property-value-no-unknown"),
    ),
  );
});

test("shared Prettier profile formats HTML and CSS", async () => {
  assert.equal(
    await prettier.check("<p>Hello</p>\n", { ...prettierConfiguration, filepath: "fixture.html" }),
    true,
  );
  assert.equal(
    await prettier.check("p {\n  color: red;\n}\n", {
      ...prettierConfiguration,
      filepath: "fixture.css",
    }),
    true,
  );
  assert.equal(
    await prettier.check("p{color:red}", { ...prettierConfiguration, filepath: "fixture.css" }),
    false,
  );
});
