# Alphus JavaScript quality profile

The JavaScript profile exports a reusable ESLint flat configuration, Prettier
configuration, and strict TypeScript compiler base for JavaScript projects. It
supports `.js`, `.jsx`, `.mjs`, and `.cjs`. The configuration owns general
JavaScript correctness and typed JSDoc rules; consumers own repository paths,
file scopes, TypeScript module settings, and application-specific rules.

Install this package and the consumer's selected command tools in the Node
development environment. Then compose the shared ESLint policy with local
rules:

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

Alphus command profiles can run ESLint and JavaScript formatting directly:

```toml
schema_version = 1
tools = ["eslint", "prettier-javascript"]
```

That profile scopes both tools to the four supported extensions. Select the
`javascript` profile to run only those checks, or compose it with other
language profiles in a consumer policy.
