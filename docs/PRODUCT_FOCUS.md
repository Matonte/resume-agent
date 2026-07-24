# Product focus (decision)

**Decision date:** 2026-07-24  
**Related issues:** [#1](https://github.com/Matonte/resume-agent/issues/1), [#2](https://github.com/Matonte/resume-agent/issues/2), [#3](https://github.com/Matonte/resume-agent/issues/3), [#4](https://github.com/Matonte/resume-agent/issues/4), [#5](https://github.com/Matonte/resume-agent/issues/5)

## Primary problem we own

**Help a candidate tailor a job application package from verified experience — without inventing facts — and carry that same evidence through application answers and interview prep.**

## Supporting bets (this horizon)

1. **Outcome-first UX** — users see identify → tailor → application answers → interview talking points, not pipeline jargon (#1, #3).
2. **Visible accuracy guarantee** — the no-invention discipline is productized in copy, badges, and docs (#2; see [ACCURACY.md](ACCURACY.md)).

## Non-goals (same horizon)

- Building a full ATS / job tracker.
- Replacing Contact / Meeting Advisor internals.
- Shipping a full “career OS” evidence platform in one go (directional only — #4).

## Epic alignment (#4)

The long-term vision remains: **one trusted evidence backbone → many hiring surfaces**.  
Near-term slices under that epic:

| Slice | Issue | Status |
|-------|-------|--------|
| Outcome framing | #1 | Shipped |
| Accuracy surface | #2 | Shipped |
| Hiring workflow coherence | #3 | Shipped |
| Deeper evidence platform | #4 | Deferred / directional |

## Ordered follow-ups

1. Keep hardening evidence IDs and review UX (already partially on `main`).
2. Prefer workflow depth (shared job context, clearer apply path) over new adjacent tools.
3. Scope the next vertical under #4 only when a concrete slice is chosen (not “platform”).
