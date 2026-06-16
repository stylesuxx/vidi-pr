You are consolidating multiple per-chunk review outputs into one final review for this pull request.

Each chunk produced its own four-section review of part of the diff. Combine them into a single review with the same four sections (`## Summary`, `## Findings`, `## Suggestions`, `## Positives`), applying all the same output rules: valid GitHub-flavored Markdown, professional tone, no emojis, no em-dashes, severity tags on findings, and every issue in exactly one section.

Rules:

- Deduplicate ruthlessly, including across sections. If the same issue appears in more than one chunk, or appears as both a finding and a suggestion, keep it once, in the single most appropriate section.
- Each finding stays one single-line bullet: `[severity]` tag in backticks, then plain prose, then `; fix: ...`. Never expand a finding into a nested "Fix:" sub-bullet.
- Resolve contradictions. Do not praise something in Positives that you also flag in Findings (for example, calling a class thread-safe in Positives while flagging it as not thread-safe in Findings). Pick the better-supported claim and drop the other.
- Preserve the severity tags. Order findings most-severe first across the whole PR.
- Keep at most the 3-5 highest-value suggestions for the entire PR. Drop generic filler. Positives is at most 2 bullets.
- Do not introduce any finding or suggestion that no chunk raised, and do not invent or alter file paths.
- Write one unified Summary for the whole change, not a concatenation of the per-chunk summaries.

Merging chunks tends to produce too many items. After combining, enforce these hard limits and delete the lowest-value items until they hold: Suggestions has at most 5 bullets; Positives has at most 2 bullets; no point appears in both Findings and Suggestions.

<chunk_outputs>

{{chunk_outputs}}

</chunk_outputs>
