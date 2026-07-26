# Accuracy guarantee

Resume Agent’s product promise:

> **Tailor your resume to a specific job without inventing experience.**

## What that means

- Claims stay grounded in **your verified experience** (the profile built from your résumés).
- We do **not invent** metrics, job titles, tools, dates, years of experience, industries, employers, or scope.
- Years of experience appear only when your profile explicitly provides them — never a default guess.
- Industry wording in summaries is kept only when your profile already supports those words.
- Tailored bullets are **evidence-backed**. If a claim cannot be tied to evidence, it is **dropped**, not guessed.
- Low-confidence inferred claims are omitted from drafts; the draft may include **clarifying questions** instead of assumptions.
- Optional “match job language” may rephrase wording to fit a posting; it still must not introduce new facts.
- Every selected bullet carries an evidence id so you can trace it back to your profile.

## Where you see it in the product

- Product promise strip on Tailor, Apply package, Today’s jobs, and Interview prep.
- Accuracy callouts on Tailor / Apply package.
- “evidence-backed” markers next to tailored bullets when a draft is generated.
- Notes under the resume draft that restate the guarantee in plain language.
- Optional `clarifying_questions` on draft API responses when key facts are missing.

## What this is not

- Not a rebuild of the evidence engine (see GitHub issue #4 for the longer-term evidence-system epic).
- Not a guarantee that every employer will agree with your framing — you still review before send.
