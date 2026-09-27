# Public glossary quality evaluation

This suite is offline by default:

```bash
uv run python -m scripts.evaluate_glossary
```

It prepares eight fixed, public cases using the production translation and
repair prompt builders. Cases compare baseline/preferred names and academic
terms, absent terms, original-target isolation, untrusted term data and the
repair prompt. Its default output is synthetic evidence, not a live quality pass.

## Limits for a live run

- GCP only; no microphone, TTS, private transcript, imported corpus or arbitrary
  fixture file.
- At most eight sequential requests, each with 200 output tokens and 2,048
  UTF-8 content bytes plus a 1,024-token role allowance.
- Models: the existing `mistral-small-latest` or `mistral-small-2603`.
- No automatic request retry or ledger replay.
- Added request-cost reservation must fit $0.01 AND the remaining $1 project
  budget, with an explicit, evidence-backed prior-cost upper bound.
- Keys are accepted only from the normal process environment or an in-memory
  standard-input channel, never command-line values, saved files or reports.
  This script does not search OpenClaw credential stores.
- Reserve estimated cost durably before each API call. An uncertain request
  retains its reservation and stops the run.
- Save only case IDs, quality/term flags, token counts, latencies and cost
  reservations. Never retain response text, keys or provider error bodies.

The reservation uses twice the current standard Small 4 rates ($0.30/$1.20
per million input/output tokens), verified against
[Mistral pricing](https://docs.mistral.ai/inference/pricing) on 2026-09-27.
UTF-8 bytes plus role allowance deliberately overestimate input tokens.
Billing and tokenizer assumptions must be checked before reuse; the ledger
does not claim access to an invoice or include unrelated account usage.

An approved live run requires all of `--live`, `--ledger`,
`--prior-cost-upper-usd` and a configured Mistral connection.
Do not invent the prior-cost bound or retry under a new ledger after an
uncertain call. The caller must reconcile cumulative reservations first.

A passing suite is a small directional check. It does not establish complete
semantic accuracy, general language quality, human playback quality, or a
production release by itself.
