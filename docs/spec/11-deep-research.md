# 11 — Deep Research

Deep research answers a question by gathering, reading, and synthesizing many web sources into a thorough, cited report, refining its understanding over multiple rounds until the answer is comprehensive.

---

## DR-1 — Capability

- **DR-1.1 (MUST).** Given a question, the system MUST research it across multiple web sources and produce a written report that answers it.
- **DR-1.2 (MUST).** Research MUST proceed iteratively: gather sources, extract relevant evidence, refine an evolving answer, and identify remaining gaps to investigate in the next round.
- **DR-1.3 (MUST).** Each source used MUST be cited in the report.
- **DR-1.4 (MUST).** A source MUST NOT be fetched more than once within a run, and the same query MUST NOT be repeated.
- **DR-1.5 (SHOULD).** A completed report SHOULD be carryable into a follow-up conversation, where the report and its findings become available context for further questions without re-running the research.
- **DR-1.6 (MAY).** Before research begins, the system MAY produce a brief research plan (sub-questions, key topics, success criteria) for the user to preview.

## DR-2 — Output

- **DR-2.1 (MUST).** The final report MUST be long-form and well-structured, with headings, an executive summary, and a concluding answer to the question.
- **DR-2.2 (MUST).** The report MUST include specific evidence (data, figures, comparisons) drawn from the sources, and SHOULD note where sources agree or disagree.
- **DR-2.3 (SHOULD).** The system SHOULD adapt the report's structure to the question type — for example a ranked list with pros/cons for product questions, a criteria table for comparisons, numbered steps for how-to questions, or an evidence-for/against verdict for fact-checks.
- **DR-2.4 (MUST).** The completed report MUST be rendered as a self-contained document. Access to it MUST remain restricted to its owner.
- **DR-2.5 (SHOULD).** Run statistics (duration, rounds, sources, queries, model, and which search providers contributed) SHOULD be available with the report.
- **DR-2.6 (MAY).** The report MAY surface representative images from its sources, and the user MAY hide or restore individual images in the rendered report.

## DR-3 — Limits & control (performance)

- **DR-3.1 (MUST — performance).** A run MUST be bounded by both a maximum number of rounds and an overall time limit, stopping at whichever comes first.
- **DR-3.2 (MUST).** The system MUST stop early once the report is judged comprehensive, after a minimum amount of research.
- **DR-3.3 (MUST).** A run MUST be cancellable. Cancellation takes effect at the next step boundary; an in-flight model call or fetch MAY finish before the run stops.
- **DR-3.4 (SHOULD — performance).** Sources within a round SHOULD be searched and read concurrently, and the number of sources read per round SHOULD be bounded.

## DR-4 — Robustness

- **DR-4.1 (MUST).** If web search returns no usable results across consecutive rounds, the system MUST conclude that search is unavailable and return a clear message rather than an empty or fabricated report.
- **DR-4.2 (MUST).** A failure in any single research step MUST NOT abort the run; the system MUST continue with what it has gathered.
- **DR-4.3 (SHOULD).** Low-value or irrelevant sources SHOULD be discarded rather than included in the report.

## DR-5 — Progress

- **DR-5.1 (MUST).** The system MUST stream progress as the run proceeds, conveying at least the current phase (planning, searching, reading, analyzing, writing) and running counts of sources and findings.
- **DR-5.2 (MAY).** The system MAY show an estimated time to completion, informed by the duration of past runs.

## DR-7 — Library

- **DR-7.1 (MUST).** Completed reports MUST be retained and listed in a browsable library that survives a restart.
- **DR-7.2 (SHOULD).** The library SHOULD support searching and sorting reports, and archiving or restoring them.
- **DR-7.3 (SHOULD).** From a completed report, the user SHOULD be able to start a follow-up conversation seeded with that report as context (see DR-1.5).

## DR-6 — Configuration

- **DR-6.1 (MAY).** Per-run limits (rounds, time, sources per round, report length) and the search provider MAY be configurable; if no provider is specified a sensible default MUST be used, and an explicitly disabled provider MUST result in no web search.
