# Human review packet: document heading style

**Packet version:** 1  
**Prepared:** 2026-11-02  
**Status:** source excerpts assembled; all human labels are pending.

This packet gives reviewers a small, mixed-context sample for #57. It contains
technical documentation, a source presentation, and marketing copy. No heading
has been assigned a quality label, and this packet is not a precision estimate.

## Reviewer worksheet

For each candidate, record the document role, whether the heading helps readers
identify the section or slide content, and whether the wording is appropriate
for that role. Use these labels only after opening the linked source and reading
the adjacent content:

| Label | Meaning |
| --- | --- |
| `descriptive` | Helps identify the topic, operation, example, result, or claim. |
| `rhetorical-useful` | Rhetorical, but useful and appropriate in its context. |
| `unclear` | Context does not establish whether the wording serves its role. |
| `not-applicable` | Boilerplate, syntax demonstration, or not a content heading. |

Keep role, label, rationale, and reviewer identity in the worksheet copy. Do not
use the detector output as a label. Review every candidate before calculating
precision, misses, or reviewer usefulness.

| ID | Source set | Candidate heading | Human label | Rationale / context |
| --- | --- | --- | --- | --- |
| T01 | Technical | Why CARE? | pending | |
| T02 | Technical | The Triadic Collaboration Model | pending | |
| T03 | Technical | Five Phases of Development | pending | |
| T04 | Technical | Phase 1 — Scope & Decompose | pending | |
| T05 | Technical | Phase 2 — Key Information Elicitation | pending | |
| T06 | Technical | Phase 3 — Reasoning Policy & Guardrails | pending | |
| T07 | Technical | Phase 4 — Prompt Architecture | pending | |
| T08 | Technical | Phase 5 — Benchmarking & Verification | pending | |
| T09 | Technical | Four Key Design Targets | pending | |
| T10 | Technical | Key Differences: CARE V1 vs CARE V2 | pending | |
| T11 | Technical | Core Principles (CARE V2) | pending | |
| P01 | Presentation | Welcome to Slides | pending | |
| P02 | Presentation | Everything is markdown | pending | |
| P03 | Presentation | Markdown components | pending | |
| P04 | Presentation | Tables | pending | |
| P05 | Presentation | Graphs | pending | |
| M01 | Marketing | A new species of product tool | pending | |
| M02 | Marketing | Purpose-built | pending | |
| M03 | Marketing | Powered by agents | pending | |
| M04 | Marketing | Designed for speed | pending | |

## Source records

### T — Technical documentation

NASA IMPACT, *AKD-CARE*, README at commit
[`0c189eb`](https://github.com/NASA-IMPACT/akd-care/commit/0c189eb53155326d0d21ad9ec7133597d058349d)
(2026-06-04). The repository identifies CARE as a staged methodology for
engineering agents in scientific and technical workflows. The headings above
come from the pinned README; the project is Apache-2.0 licensed. Review each
heading with its following paragraph or list, not from the title alone.

### P — Presentation source

Maas Lalani, `slides` repository, [`examples/slides.md` at commit
`92af1ef`](https://github.com/maaslalani/slides/blob/92af1ef1f33a75bd51db9842a760bd228f3b1a61/examples/slides.md)
(2026-07-08). This is a Markdown-authored terminal presentation example from a
MIT-licensed repository. The source includes code, Markdown feature demos,
tables, and a graph. Some headings may be demonstration labels rather than
claims or ordinary content titles; determine that from adjacent slide content.

### M — Marketing page

Linear homepage, [linear.app](https://linear.app/), retrieved 2026-11-02. This
live page presents a product and its positioning. The four short heading
excerpts above were visible in the page at retrieval time. The page is not
version-pinned and may change; reviewers should record the retrieval date and
save an authorized local snapshot if repeatability is required.

## Review limits

The technical and presentation sources are pinned; the marketing page is not.
This is a purposive convenience sample, not a representative corpus. It does
not establish authorship, technical correctness, universal heading quality, or
detector precision. A separate reviewer should assign labels before using these
examples to calibrate a rule or discuss enforcement.
