# Alphus JavaScript quality profile

The JavaScript profile exports a reusable ESLint flat configuration, Prettier
configuration, and strict TypeScript compiler base. The general ESLint profile
supports `.js`, `.jsx`, `.mjs`, and `.cjs`. Optional React and Angular profiles
add framework rules and TypeScript parsing. Consumers own repository paths,
TypeScript module settings, and application-specific rules.

Install this package and the consumer's selected command tools in the Node
development environment. Alphus invokes the selected tools through local
`npm exec`. Then compose the shared ESLint policy with local rules:

```js
import alphusJavaScript from "@alphus/javascript-quality/eslint";

export default [...alphusJavaScript];
```

Use the shared Prettier and TypeScript settings from the consumer configs:

```js
export { default } from "@alphus/javascript-quality/prettier";
```

```json
{
  "extends": "@alphus/javascript-quality/tsconfig",
  "compilerOptions": { "module": "NodeNext", "moduleResolution": "NodeNext" },
  "include": ["src/**/*.js", "src/**/*.jsx", "src/**/*.mjs", "src/**/*.cjs"]
}
```

The shared package tests use synthetic source fixtures. They cover each source
suffix, JSDoc requirements, CommonJS parsing, formatter settings, and strict
JavaScript compiler options without depending on any consumer repository.

## React

Install `@eslint-react/eslint-plugin`, `eslint-plugin-react-hooks`, and
`typescript-eslint` in a React consumer. Add the opt-in profile after the
general JavaScript profile:

```js
import alphusJavaScript from "@alphus/javascript-quality/eslint";
import alphusReact from "@alphus/javascript-quality/eslint/react";

export default [...alphusJavaScript, ...alphusReact];
```

The React profile applies the maintained React rules and the official Hooks
rules to JavaScript and TypeScript, including JSX and TSX. It lets the official
Hooks plugin own `rules-of-hooks` so one violation gets one report. It does not
require a React runtime dependency inside Alphus. A consumer can override rule
levels after these arrays or wrap the profile in a file-scoped ESLint config.

## Angular

Install `angular-eslint` and `typescript-eslint` at versions compatible with
the consumer's Angular and ESLint versions. The current Alphus package is
checked against `angular-eslint` 22.6 and `typescript-eslint` 8.72. Add the
Angular profile to the consumer's flat config:

```js
import alphusAngular from "@alphus/javascript-quality/eslint/angular";

export default [...alphusAngular];
```

The Angular profile applies recommended TypeScript rules to `.ts`, recommended
and accessibility template rules to `.html`, and processes inline component
templates. Selector prefixes, project-aware type checking, and rule overrides
remain consumer choices. ESLint must run on both `.ts` and external `.html`
files to cover both template forms.

## Standard HTML and CSS

For ordinary HTML documents, install `html-validate` and use its config in a
consumer `.htmlvalidate.mjs`:

```js
export { default } from "@alphus/javascript-quality/html-validate";
```

The config combines HTML-validate's recommended, document, and Prettier
compatibility presets. It checks markup and accessibility while leaving
formatting to Prettier. Use `tools = ["html-validate", "prettier-html"]` to
run both against `.html` files. Keep Angular templates on the Angular ESLint
profile instead of selecting this generic HTML gate for them.

For CSS, install `stylelint` and `stylelint-config-standard`, then use a
consumer `stylelint.config.mjs`:

```js
export { default } from "@alphus/javascript-quality/stylelint";
```

Use `tools = ["stylelint", "prettier-css"]` for `.css` files. The Stylelint
rules catch errors and conventions; Prettier owns formatting. Consumer configs
can extend these exports with project rules and file exclusions. SCSS and
embedded CSS need their own syntax or extraction plugins and are outside
these CSS file scopes.

Alphus command profiles can run ESLint and JavaScript formatting directly:

```toml
schema_version = 1
tools = ["eslint", "prettier-javascript"]
```

That profile scopes both tools to the four supported extensions. Select the
`javascript` profile to run only those checks, or compose it with other
language profiles in a consumer policy.

React projects with TypeScript can add `eslint-typescript` and
`prettier-typescript`. Angular projects can add those plus
`eslint-angular-template` for external HTML templates. The extra tools are
opt-in, so a plain JavaScript consumer need not install a framework parser or
lint plugin. The `typescript` and `html` Alphus profiles can run these scopes
independently, while `check` runs all selected tools. Standard HTML and CSS
projects can select the separate tools above; `css` is a distinct profile.
