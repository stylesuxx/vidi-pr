# Running vidi-pr against a local LLM

vidi-pr talks to any OpenAI-compatible chat endpoint, so you can point it at a
model running on your own hardware (llama.cpp, vLLM, LM Studio, Ollama, etc.).
This document records what actually moves review quality on small, local models,
the hard limits you will hit, and how far you can tune past them.

The findings below were gathered against `qwen2.5-coder-7b-instruct` (Q4_K_M)
served by llama.cpp with a **16384-token** context, reviewing real pull
requests. Numbers will differ for your model, but the levers are the same.

## The dry-run inspector

You do not need to post to a real PR to evaluate prompts and settings. The
`dry-run` subcommand runs the full review pipeline (fetch, filter, chunk,
per-chunk review, synthesis, render) and prints the review that *would* be
posted, without posting it:

```sh
# Public PR, with a token to avoid GitHub's 60 req/hr anonymous limit
GITHUB_TOKEN=ghp_xxx uv run python -m vidi_pr dry-run \
  https://github.com/owner/repo/pull/123 \
  --config /etc/vidi-pr/vidi-pr.yml \
  --dump-prompts
```

- The rendered review body goes to **stdout**; a summary (model, chunk count,
  token usage, duration) and, with `--dump-prompts`, the exact messages sent to
  the model go to **stderr**.
- Auth comes from `GITHUB_TOKEN` or `VIDI_PR_GITHUB_TOKEN`; without one, only
  public PRs are reachable and you share the low anonymous rate limit.
- `--config` accepts your real operator YAML (only the `llm`, and optionally
  `pipeline` and `defaults`, sections are used) or a minimal file with just an
  `llm:` block.
- `--context "..."` injects extra project context into the prompt, for testing
  how context affects output (see below).
- URLs may be `https://github.com/owner/repo/pull/N` or `owner/repo#N`.

Iterate on a **small** PR (one chunk) for fast turnaround, then validate the
winning settings on a large one.

## The hard limit: context window

This is the first wall you hit, and it is not subtle. The model's context window
must hold the **entire prompt** (system prompt + PR metadata + diff) *plus* the
completion. The pipeline packs files into chunks of `pipeline.max_chunk_chars`
characters; the default is `80000`, which is roughly 20k tokens of diff before
any overhead.

On a 16k-context server that overflows instantly. A mid-size PR (≈66k chars of
diff, ≈16.6k tokens) packed into one default-sized chunk produced a ~19.7k-token
prompt and the endpoint rejected it outright:

```
LLM endpoint returned 400: request (19733 tokens) exceeds the available
context size (16384 tokens)
```

Two consequences:

- **`max_chunk_chars` must be sized to your context window, not left at the
  default.** A workable rule of thumb: keep the per-chunk diff under roughly
  `(context_tokens - 3000 overhead - max_tokens) * 3.5 chars/token`. For a 16k
  context with `max_tokens: 3500`, that is ~28000 chars.
- **`max_tokens` is the completion budget and is subtracted from the same
  window.** The stock `max_tokens: 16384` reserves the *entire* 16k context for
  output, leaving nothing for the prompt. For a non-reasoning model, 3000-4000
  is plenty for a review; reserve the rest for the diff.

The single highest-value infrastructure change is **raising the server's context
window** (llama.cpp `-c 32768` or higher; qwen2.5-coder-7b supports up to
32768 natively). A bigger window lets a whole PR fit in one chunk, which, as the
next section shows, is where quality lives.

## The biggest quality lever: an anti-repetition penalty

Small quantized models fall into **repetition loops**. With the stock settings
(no penalties), a single-chunk review derailed into emitting an unbounded list
of line numbers until it hit the token cap:

```
[high] ... redundant null checks ... (Line 292, 300, 308, 316, 324, 332, 340,
348, 356, 364, 372, 380, 388, 396, 404, 412, 420, ... )   <- ran to max_tokens
```

Adding a frequency penalty via `llm.extra_body` eliminated the loop and, as a
bonus, made the output dramatically tighter and faster:

```yaml
llm:
  extra_body:
    frequency_penalty: 0.7
    presence_penalty: 0.1
```

The same PR that produced the line-number garbage above (115s, truncated)
reviewed cleanly in **8 seconds** with two grounded findings once the penalty
was in place. If you take one thing from this document for a small local model,
take this: **set a frequency penalty.** `0.5-0.8` is a good range; too high and
the model starts code-switching (we saw the occasional stray non-English token
at `0.7`).

## Chunking: fewer, larger chunks win

It is tempting to chunk aggressively (even one file per chunk) so each request is
small. On a small model this makes reviews **worse**, not better.

Each chunk is reviewed in isolation, then a synthesis pass merges the per-chunk
outputs. The problem is that an isolated chunk cannot see the rest of the PR, so
the model fills the gaps with confident speculation, and the synthesis pass
cannot retract a hallucination it was handed.

A controlled comparison on one PR (same model, same prompts, only the chunk
count changed) makes this concrete:

- **One chunk:** two tight, grounded findings; suggestions correctly suppressed;
  no duplication.
- **Four chunks:** four findings including a speculative "race condition" and a
  vague null-safety hand-wave, three generic suggestions that should have been
  suppressed, and the same null-safety point listed in *both* Findings and
  Suggestions.

A larger refactor PR split into three chunks went further and produced findings
that **contradicted each other across sections**: it flagged a class as not
thread-safe in Findings while praising it as thread-safe in Positives.

Note that the synthesis pass does not reliably clean this up. Even with explicit
synthesis-prompt rules to deduplicate across sections and drop filler, the small
model reintroduced both on the four-chunk run. Synthesis quality is itself a
small-model weakness, which is one more reason to avoid multi-chunk reviews.

Guidance:

- Prefer settings that keep a PR in as **few chunks as possible** (large
  `max_chunk_chars`, bounded only by the context window).
- Do **not** chunk per file. More chunks means more isolated speculation and a
  harder synthesis job.
- If a PR is too big to fit even one chunk on your context window, that is a
  signal to raise the context window, not to shrink the chunks.

## Context injection: helps aim, amplifies hallucination

Per-repo `review.project_context` / `focus`, and the `--context` flag, steer the
review. On a small model this is double-edged.

Giving the model a focus list that included "thread-safety in the Android UI"
did make it look there, but it **manufactured a race condition** that the
no-context run never raised and that is not supported by the diff. The model
treats a focus area as an instruction to find something in that area, and a small
model will invent one rather than report nothing.

Guidance:

- Provide **factual** context (what the system is, the stack, conventions). It
  improves relevance with little downside.
- Be cautious with imperative **focus lists** ("look for race conditions",
  "check for security holes"). On a small model they bias toward fabricating
  findings in those categories. Reserve them for larger models.

## Are small models good enough?

Yes, with the caveats above. A well-tuned 7B coder model produces genuinely
useful reviews of small-to-medium PRs: it catches unused variables, missing
null checks, getters without setters, and similar concrete issues, and with the
tuned prompts it tags severity and stays terse. The stock configuration is what
makes a small model look hopeless, not the model itself.

The floor is set by two things you cannot prompt away:

1. **Confident hallucination on complex changes.** On a multi-file refactor the
   7B invented base-class changes ("no longer inherits from `threading.Thread`"),
   nonexistent imports, and speculative race conditions, even with explicit
   prompt rules forbidding exactly that. The prompt rules reduce the rate; they
   do not eliminate it. Larger models (14B+, and especially 32B+) hallucinate
   noticeably less.
2. **Context window.** A small window forces chunking, and chunking degrades
   quality (above). This is a hardware/serving limit, not a model-intelligence
   limit, and it is the one you can most directly buy your way out of.

## Recommended starting points

Minimal tuning config for a 16k-context local endpoint (usable as `--config`):

```yaml
llm:
  provider: openai_compat
  base_url: http://your-host:8093/v1
  model: your-model.gguf
  temperature: 0.1          # low, for stable/repeatable output
  max_tokens: 3500          # completion budget; leaves room for the diff
  extra_body:
    frequency_penalty: 0.7  # the anti-repetition lever; do not skip
    presence_penalty: 0.1

pipeline:
  max_chunk_chars: 28000    # sized so one chunk fits a 16k context
  max_chunks: 8
```

If you can raise the server context window, do that first, then raise
`max_chunk_chars` to match so more PRs review in a single chunk.

| Symptom | Most likely cause | Fix |
| --- | --- | --- |
| `exceeds the available context size` 400 | `max_chunk_chars` and/or `max_tokens` too large for the window | lower both; raise server `-c` |
| Output loops / repeats / runs to the token cap | no anti-repetition penalty | add `frequency_penalty: 0.5-0.8` |
| `finish_reason: length`, empty answer | reasoning model ate the budget, or `max_tokens` too small | raise `max_tokens`, or disable reasoning |
| Findings contradict each other | too many chunks | raise `max_chunk_chars`; raise context window |
| Invented files/classes/imports | model-capability floor | tighten prompts (helps partially); use a larger model |
| Stray non-English tokens | penalty too high | lower `frequency_penalty` |
