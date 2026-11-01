# Open issue priorities

This order weighs adoption impact, reproducibility, and dependency order. The
first implementation slice for an issue does not imply that its later,
separately scoped proposals have shipped.

## Ranked work

1. **Bound the Lizard worker transport** ([#44](https://github.com/sheepfling/alphus/issues/44), section 1). This addresses a reported Windows launch failure and has a source-backed scaling risk. Implement it on a base that contains the cyclomatic-complexity gate. The current `feature/pydantic-practices-expansion` checkout predates that gate, so this change cannot be made here without importing a large, unrelated feature stack.
2. **Add lexical source-family review** ([#45](https://github.com/sheepfling/alphus/issues/45), section 1). This is useful as an opt-in advisory and can be added independently. Implemented in this checkout as the provisional `source-families` rule; it does not infer cohesion or recommend file moves.
3. **Improve report discoverability and early-failure exports** ([#44](https://github.com/sheepfling/alphus/issues/44), section 2). Build on the existing profile JSON and history contracts after working from the issue's target baseline. Keep operational failure, findings, confidence, policy, and child exit distinct.
4. **Improve grouped diagnostic evidence and scope visibility** ([#44](https://github.com/sheepfling/alphus/issues/44), section 3). Preserve native identities and distinguish occurrences, sites, grouped items, and families before changing presentation.
5. **Evaluate the proposed C++ advisories** ([#44](https://github.com/sheepfling/alphus/issues/44), section 4). This is lower priority because the issue describes maintainability proposals rather than reproduced runtime failures. Record precision and tool capability before shipping new rules.
6. **Evaluate semantic and history evidence for source families** ([#45](https://github.com/sheepfling/alphus/issues/45), section 2). This depends on language-specific dependency/import analysis and representative consumer evidence. Keep it separate from the lexical rule until that evaluation supports it.

## Current checkout status

The source-family rule is configured for the `review` profile with provisional
rollout. Its inventory and output are bounded, its findings state the lexical
uncertainty, and it reports incomplete scans. The focused test set and review
profile pass in this checkout.

The Lizard transport and the reporting follow-ups are not complete here. The
current branch is an ancestor of the target baseline identified by issue #44;
its source tree has no cyclomatic-complexity or Lizard implementation to patch.
Applying the missing baseline would bring in hundreds of unrelated files, so
continue those slices after rebasing this work onto the issue's current base.
