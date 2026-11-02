# Heading style pilot

## Scope

This review-only sample is pinned to `sheepfling/styling` revision
`e73e7a006820de142f11cc9fffb46cb656ea1164` on
`codex/brian-typography-backlog`. It covers the six public Markdown files named
in issue #57's pilot proposal. The extractor found 14 structural headings. This
is a small convenience sample, not a repository-wide result or a validated
precision estimate. For each heading, I also checked the following paragraph
or list when present to judge whether terse titles such as "Required slots"
and "Build and review" had clear local context.

## Human-label status

No human labels have been collected. An earlier pass annotated the 14 headings
as descriptive-looking after inspecting nearby text, but there is no independent
review evidence for those judgments; they are withdrawn as validation labels.
The sample has no clearly rhetorical heading, no presentation deck, no marketing
slick, and no LaTeX or HTML source, so it cannot measure misses or false
positives for those contexts. No private proof packet or customer copy was
inspected.

## Synthetic fixture candidates

Use synthetic data to cover the absent cases without copying brand material:

- Positive technical outline: repeat `From X to Y` headings and `What X Reveals`
  headings across at least eight sections; expect one density advisory per
  repeated family with source lines and example titles.
- Positive technical outline: repeat paired imperative headlines such as
  `See the Heat. Reveal the Change.` and `Measure the Shift. Find the Cause.`;
  use multiple occurrences to test density instead of banning a single title.
  The current detector includes this family, but the public sample has no such
  titles.
- Negative: a technical outline with descriptive section names and one
  rhetorical transition; expect no finding.
- Negative: a synthetic marketing slick that intentionally uses slogans; keep
  it outside the technical profile or select a separate policy with a higher
  density threshold.
- Negative: a presentation with evidence-backed assertion titles; expect no
  finding solely because a title makes a claim.

## Limits and follow-up

A separate mixed-context review packet is available in
[heading-style-review-packet.md](heading-style-review-packet.md). It contains
source excerpts and blank human-label fields for technical documentation, a
presentation example, and marketing copy. Its labels remain pending; it is not
an extension of the unverified preliminary annotations described above.

This sample supports only the narrow statement that the current scanner leaves
these selected technical headings unflagged at the configured threshold. It
does not establish that they are descriptive, document clarity, authorship,
recall, or suitability for enforcement. A fuller pilot needs independently
reviewed technical, marketing, and presentation examples with human labels. The
synthetic positives are fixture candidates, not human-labeled examples from the
inspected corpus.
