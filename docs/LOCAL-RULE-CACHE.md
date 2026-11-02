# Opt-in local rule cache

Alphus provides a narrowly scoped persistent cache for direct
`output-escaping` rule runs. It is disabled unless `--local-cache` is supplied:

```sh
alphus --root . --config quality-gates.toml --rule output-escaping \
  --local-cache /tmp/alphus-output-escaping-cache.json
```

The cache stores only per-file finding records and SHA-256 content digests; it
does not store source text. A hit requires the same canonical repository root,
relative path, exact file bytes, effective `output-escaping` policy, cache
schema, and rule implementation version. Added files miss, deleted/unselected
paths are pruned, and policy or rule-version changes invalidate prior entries.
Cache writes use an atomic replace. The command reports hits, misses, pruned
paths, invalidation, and save status on stderr so `--json` stdout remains the
existing findings array.

Use `--force-fresh` with `--local-cache` to bypass every hit and replace the
cache with fresh scan results:

```sh
alphus --root . --config quality-gates.toml --rule output-escaping \
  --local-cache /tmp/alphus-output-escaping-cache.json --force-fresh
```

This pilot is limited to a direct `--rule output-escaping` invocation. It does
not apply to profile runs, cross-file rules, or external tools. It still reads
selected files to hash their contents; it saves the Python/JavaScript analysis
for unchanged files, not filesystem reads. A failed scan does not write partial
results. Cache artifacts should be kept outside the source inventory. The
rule-version constant must be incremented when scanner behavior changes.

## Local measurement

On the Alphus checkout at `f4c0de087437a60ba555f9bce5cd7c7d03d2c902`, the
`output-escaping` policy considered 327 inventory paths and analyzed 235
Python files after its own extension/exclusion filters. On macOS 26.6.2 with
Python 3.12.14, nine uncached and nine warm-cache runs had median times of
0.225745 s and 0.005299 s respectively; findings were identical. This is one
local measurement, not a downstream benchmark or a general speed guarantee.
