# Open issue priorities

This order weighs adoption impact, reproducibility, and dependency order. The
first implementation slice for an issue does not imply that its later,
separately scoped proposals have shipped.

## Ranked work

1. **Bound the Lizard worker transport**
   ([#44](https://github.com/sheepfling/alphus/issues/44), section 1).
   This addresses a reported Windows launch failure and has a source-backed
   scaling risk. PR [#63](https://github.com/sheepfling/alphus/pull/63) is open
   against `main`.
2. **Add lexical source-family review**
   ([#45](https://github.com/sheepfling/alphus/issues/45), section 1).
   This is a bounded, provisional advisory that does not infer cohesion or
   recommend file moves. PR [#64](https://github.com/sheepfling/alphus/pull/64)
   is open against `main`.
3. **Improve report discoverability and early-failure exports**
   ([#44](https://github.com/sheepfling/alphus/issues/44), section 2).
   Preserve the distinction among operational failure, findings, confidence,
   policy, and child exit. PR
   [#65](https://github.com/sheepfling/alphus/pull/65) is open against `main`.
4. **Improve grouped diagnostic evidence and scope visibility**
   ([#44](https://github.com/sheepfling/alphus/issues/44), section 3).
   Preserve native identities and distinguish occurrences, sites, grouped
   items, and families before changing presentation.
5. **Evaluate the proposed C++ advisories** ([#44](https://github.com/sheepfling/alphus/issues/44), section 4).
   Record precision and tool capability before shipping new rules; the issue
   describes maintainability proposals rather than reproduced runtime failures.
6. **Evaluate semantic and history evidence for source families**
   ([#45](https://github.com/sheepfling/alphus/issues/45), section 2).
   This depends on language-specific dependency/import analysis and
   representative consumer evidence. Keep it separate from lexical review.

## Current checkout status

PRs #63, #64, and #65 cover the first slices of these issues and remain
unmerged. The grouped-diagnostic and semantic/history proposals remain
separately scoped follow-up work.
