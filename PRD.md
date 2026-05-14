# Gander — PRD

**Version:** v0.11 (PRD, +observability)
**Owner:** Martin (candidate)
**Submission deadline:** 15 May 2026

---

## 1. Context

This product is a candidate submission for an AI-first developer hiring case study. The hiring company will evaluate it against six stated priorities (in their order):

1. Willingness to invest 6–12h
2. Ability to build an AI pipeline
3. A clean Python deliverable they can run themselves
4. Creativity in sourcing data and choosing approaches
5. Prompt design and pipeline sequencing
6. End-to-end runnability — explicitly gates round 2

The product is the artifact graded in round 1. In round 2, the same reviewer will share-screen and run the pipeline on a CV they provide.

## 2. Users

- **Primary:** the hiring reviewer in round 1 — needs to evaluate the submission with minimal effort.
- **Secondary:** the same reviewer in round 2 — needs to run the pipeline live on their own CV data.

## 3. The product, in one sentence

Upload a CV; receive a defensible seniority score, a market-grounded salary range, and a CV-specific plan to grow that salary by 30%.

## 4. Functional requirements

### 4.1 Input
The system accepts a CV as a PDF or DOCX file.

### 4.2 Output: Seniority Score
- Integer, 0–100.
- Composed of named components covering, at minimum: skills, experience, education, soft signals (the four dimensions named in the brief).
- The aggregation is transparent — the user can see how the components combine.
- Each component carries a justification grounded in specific CV content.

### 4.3 Output: Salary Estimate
- A range, presented in a clearly stated unit (currency + time period). Choice of unit should reflect the candidate's market and the underlying source data.
- Anchored in market data fetched at request time, not from a hardcoded table.
- Cites the sources the estimate is built on.
- Reports confidence on a Low / Medium / High scale, with **explicit criteria** for each tier (e.g., number of independent sources, agreement across them, recency) — not left to the judge's discretion alone. **Confidence is judged independently of the estimate itself** — the assessment of whether the underlying data was sufficient is made by a separate reasoning step, not by the same model that produced the number. This is to prevent the estimator from grading its own work.

### 4.4 Output: Explanation & +30% Growth Plan
- Strengths and gaps relevant to the candidate's current band.
- A concrete set of actions to grow salary by 30%, each with: what to do, time horizon, and the mechanism by which it moves the salary needle. **Actions must be achievable within ~12–24 months given the candidate's current position** — recommendations like "complete a PhD" or "found a unicorn" fail this test.
- All explanations must reference specific CV content. Generic statements that could apply to any CV ("learn more skills," "improve communication") are a non-conformant output.

### 4.5 Hallucination guard
Every claim about the candidate must be grounded in a quoted phrase from the source CV, **and the quoted phrase must be programmatically verifiable as a substring of the extracted document text**. A model-produced "quote" that doesn't actually appear in the source is treated as a verification failure. Unverifiable claims are dropped from the output — the user-visible result is a shorter list of strengths/gaps/components, not a placeholder or fabricated content.

### 4.6 Failure handling
The user sees clear, useful messages — not stack traces or empty UIs — in these cases:

- **Corrupt or unreadable file:** "Unable to read this file. Please upload a valid PDF or DOCX."
- **Image-only / scanned PDF:** "This appears to be a scanned PDF. Text-based PDFs and DOCX are required."
- **Salary search returns no usable data:** the salary block shows "Insufficient market data for this profile" with confidence Low; the rest of the report renders normally.
- **A model output fails parsing after retry:** the affected output block shows "Could not generate this section reliably," other blocks render. The system never crashes the whole report when one stage fails.

### 4.7 Bias mitigation
CV evaluation is classified as high-risk AI under the EU AI Act and is well documented to encode demographic bias (gender, age, ethnicity, class via school names and language patterns). This product addresses the issue at two levels:

- **Structural mitigation (required):** Personally identifying information — name, photo, contact details, address, dates that imply age — is redacted from the input before it reaches the scoring stage. The scoring model evaluates skills, experience, education credentials, role progression, and soft signals only.
- **Acknowledged limitation:** Some bias-encoding signals (school names, language patterns, employer prestige) cannot be fully neutralized without degrading legitimate signal. This is not resolved in v1, and the system is not validated for fairness across protected groups.

The README "Decisions" section calls this out explicitly. Outputs are framed as candidate hypotheses for the reader to validate, not as authoritative judgments.

### 4.8 Observability
Each pipeline stage emits a structured log entry containing stage name, duration, and key counters (claims verified, claims dropped, search results returned, confidence tier assigned). The UI surfaces stage transitions during processing so the reviewer sees concrete activity, not an opaque wait. Errors include sufficient context — traceback, stage, input fingerprint (file size and type, not CV content) — to diagnose without rerunning.

## 5. Acceptance criteria

The submission is done when:

1. A reviewer with no prior context produces a complete report on their own CV in under a minute, with **no setup required** to start.
2. The same submission is also runnable locally with one or two commands on a clean Python environment (round 2 share-screen path).
3. The system works on **arbitrary CVs the reviewer supplies** during round 2 — not just bundled samples.
4. On a test set of three CVs spanning seniority levels, outputs differentiate concretely: **scores span at least 30 points across the set**, **the salary ranges of the most-junior and most-senior CVs do not overlap**, and **no growth-plan item appears verbatim across CVs**.
5. Spot-checking three explanations confirms each is grounded in specific, programmatically-verified phrases from its source CV — not portable to a different CV.
6. Salary outputs include working source URLs for the reviewer to verify.

## 6. Out of scope

- Authentication, accounts, history, persistence
- Batch or multi-CV processing
- OCR for image-only / scanned PDFs (acceptable to fail loudly)
- Mobile UI
- Localization beyond a single chosen UI language

## 7. Constraints

- **Build budget:** ~1 day of focused work.
- **Submission format:** Git repo or ZIP, with a README that covers how to run, how the pipeline works, and what was decided.
- **Zero-setup access:** the reviewer must be able to evaluate the system without installing anything. (Round 2 still requires a local-run path.)
- **End-to-end latency:** a CV-to-report round-trip should complete in roughly a minute on a normal connection.

## 8. Risks (product-level)

- **First-impression latency.** If the zero-setup access path has any cold-start delay, the reviewer may interpret slowness as breakage. The product must signal "working" during any wait, not appear frozen.
- **Salary grounding is non-deterministic.** Market data quality varies by role and locale. The system must handle this honestly via confidence reporting rather than masking gaps with confident-sounding numbers.
- **Generic explanations are the default LLM failure mode.** Most off-the-shelf CV tools produce slop on the recommendations. The CV-specificity requirement (§4.4) is the main quality discriminator vs. competing submissions.

## 9. What "good" looks like to the reviewer

After the reviewer touches the submission — both the zero-setup demo and a code skim — the thought you want them to have:

> "Pipeline is small but every piece is there. The recommendations are specific to the CV, not boilerplate. Decisions are deliberate and explained. Round 2."

This is a senior submission. The README "Decisions" section should read accordingly — less hand-holding, more visible tradeoff thinking, deliberate cuts noted with brief rationale.

The discriminator at this stage is judgment + reliability, not skill ceiling. Anything in the build that doesn't serve those two qualities is decoration.

---

*Implementation choices — model selection, deployment target, framework, libraries, file structure, test approach — are deliberately not specified here. Those are engineering decisions for the implementer.*
