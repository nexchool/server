# ADR-020 — How an Examination Result Is Computed

## Status

Accepted — implemented 2026-08-16 (`modules/examinations/results_service.py`,
`tests/test_examination_results.py`). No migration.

---

## Date

2026-08-16

---

# Context

ADR-018 settled what a result *is* — a frozen snapshot, versioned, never
edited — and deliberately left open how one is computed:

> "**Calculation and storage are separate.** How a result is computed —
> weighting, best-of-N, whether a failed subject caps the aggregate — is a
> service concern that will change as schools ask for it."

The discovery audit reached the same place from the requirements side, and said
so more bluntly (§NXS-73 ¶7): "is it a simple sum, weighted, best-of-N, or does
a failed subject cap the aggregate? Boards differ sharply here. **UNKNOWN —
needs a product decision.**"

That gap was real, and it was load-bearing. `exam_results` had existed since
migration 114 with **no writer at all**: every reference outside the model was a
test inserting literal figures. `paper.weight`, `paper.pass_marks` and
`component_label` each had zero readers. A first writer had to decide six
things, and guessing any of them would have baked one board's policy into every
school.

The decisions below were taken as product decisions and are recorded here so
they are arguable rather than archaeological.

---

# Decision

## A. The five mark states stay five

| State | Numerator | Denominator | Rationale |
|---|---|---|---|
| `present` | its marks | `max_marks` | including a genuine 0 |
| `absent` | 0 | `max_marks` | measured against what they could have scored |
| `malpractice` | 0 | `max_marks` | distinct from absent in the snapshot; does **not** by itself force failure |
| `exempted` | — | — | leaves the calculation entirely, so an exemption can never lower a percentage |
| *no mark row* | — | — | `not_yet_entered`; makes the result **incomplete** |

`not_yet_entered` is the sixth state and the only one that is the *absence* of a
row rather than a value in one. It never becomes a zero and never becomes an
absence — turning a teacher's unfinished register into a failed student is the
specific mistake EX-02A's status column was built to make impossible, and it
would be undone here if the engine defaulted a missing row to anything.

No synthetic `ExamMark` is ever created to represent it.

## B. Pass and fail is three-valued

```
band_pass  = resolved_band.is_pass          (None when no band resolves)
paper_pass = every applicable non-exempted paper that defines pass_marks meets it
                                            (None when no such paper exists)
is_pass    = band_pass AND paper_pass, ignoring whichever is None
           = None when both are None
```

A student can therefore fail on one subject while the aggregate passes, which is
an ordinary Indian school rule. Exempted papers create no paper-level failure,
because they are not in the calculation at all.

`is_pass = None` is a real answer, not a missing one: with no bands and no pass
marks, nothing the school configured decides the question, and inventing an
answer is worse than reporting that none exists. All three values are recorded
in the snapshot so a marksheet can say *why*.

## C. Weighting is refused, not guessed

A paper carrying a non-null `weight` refuses the whole calculation with
`WEIGHTED_CALCULATION_UNSUPPORTED`.

`weight`'s mathematics were never established, it is the one paper column
`add_papers` accepts **without validation**, and `numeric` will store `NaN` in
it. Ignoring it would silently produce an unweighted result for a school that
asked for a weighted one; consuming it would run arithmetic on a value nothing
checked. Refusing is the only option that cannot be wrong, and it is loud.
Weighted aggregation is a later slice (debt 52).

## D. Incomplete examinations calculate

EX-02A deliberately allows a paper to be locked with marks outstanding, so
"locked" does not mean "complete". Calculation is therefore never blocked by
missing marks. The snapshot carries `complete: true|false` plus a per-paper
`not_yet_entered` flag, which is what EX-03B will refuse publication on.

## E. Grading is percentage-based, resolved once, frozen

Bands are matched on the **rounded** percentage, inclusive at both ends
(`min_value <= p <= max_value`).

- **No scheme, or a scheme with no bands** — legal. No grade, no complaint: a
  school that reports marks only still has a scheme.
- **A gap** — no grade, and a warning in the snapshot. Choosing the nearest band
  would be inventing policy the school did not write down.
- **An overlap** — the lowest `sequence` wins (ties broken by id), and the
  snapshot records that the configuration was ambiguous. The database permits
  overlaps; repairing them is not this slice's business, but behaving the same
  way every time is.

The resolved band's id, label, bounds, `is_pass` and `grade_point` are **copied
into the snapshot**. A result is never re-graded on read. This is ADR-018's rule
made operational: a school redrawing its bands in December must not change what
was computed in August.

## F. Rounded once, and the stored number is the graded number

```
percentage = (total_obtained / total_max * 100) quantized to 3 dp, ROUND_HALF_UP
```

Computed in `Decimal`, never float. One rounding, at the aggregate — never at
paper level, never twice. The rounded value is what is stored in
`percentage` (`Numeric(6,3)`) **and** what the bands are matched against, so a
marksheet printing 90.000 beside an "A" is impossible.

`ROUND_HALF_UP` rather than Python's `round()`, whose banker's rounding would
make exact-half cases depend on the preceding digit — a school cannot explain
that to a parent.

**`total_max == 0` yields `percentage = None`**, not 0% and not 100%. The real
case is a student exempted from everything, and 0% would say they failed every
paper they were excused from.

## Versioning: an unpublished result is replaced, not versioned

First calculation writes `version = 1, is_current = true, published_at = NULL`.
Recalculating an **unpublished** result overwrites that row in place.

A version is a statement the school made. A result nobody has been told about is
not one, and versioning every recalculation would reach version 40 before
publication with nothing to show for it. ADR-018's freeze rule is specific: "no
row is updated **once published**". A published result refuses recalculation
outright (`RESULT_PUBLISHED`); revising one is `revision_service`, below.

*(This line named a slice number twice and was wrong both times — first
"EX-03B", then "EX-04", which is the repository roadmap's scheduling UI.
Naming the service instead is what stops it going stale a third time.)*

## Publication (EX-03B)

Publication is a separate act with its own door, `publication_service.
publish_results`, answering to **`examination.publish`** — not
`assessment.manage`, which is the key for running marking. Whoever closes a
register is not necessarily whoever tells the parents.

It computes nothing. It checks that every result is fit to be stated, stamps
`published_at`/`published_by_user_id`, moves the examination through the one
lifecycle table, and records `ResultsPublished` once — all in a single
transaction, because a school that has told half a class cannot afterwards say
which half.

**The cohort is `examination_cohort`** — the union of `paper_cohort` across the
examination's papers, the same set `calculate_results` uses. Every student in it
must have a current result, and publication never calculates on somebody's
behalf: doing so would make publication a moment when the figures can still
change.

Three conditions refuse:

- `RESULT_MISSING` — a student in the cohort has no calculated result.
- `RESULT_INCOMPLETE` — `snapshot.complete` is false. "Not yet entered" cannot
  become the school's word.
- `GRADE_UNRESOLVED` — the examination names a scheme with bands and none
  covered this percentage.

That last one is deliberately **not** "refuse when `is_pass` is None". §B above
makes `is_pass = None` a legitimate answer for a school that configured no pass
rule at all, and a blunt rule would leave a marks-only school permanently unable
to publish. The distinction is between *no rule was configured* (publishable)
and *a rule was configured and failed* (refused).

An examination whose cohort is empty publishes with zero results and says so in
the event. The alternative would strand it in marks entry with only
cancellation available.

Concurrency is handled by `with_for_update()` on the examination row — the
repository's existing convention — so a second publisher waits, re-reads
`published`, and is refused by the transition table like any other late caller.

## Revision (EX-03C)

A published result is immutable forever. A genuine error found after
publication is answered by **adding a version**, never by editing one — which
is ADR-018's rule made operational a second time.

**The trigger is an approved correction decided after publication.** EX-02B's
correction workflow, previously refused on a published examination, is now
allowed there: it changes the *mark*, and deliberately does not touch the
published result. That leaves a window in which the marks and the published
figures disagree, and the window is the point — reconciling them is a decision
somebody takes, not a side effect of approving a correction.
`revision_service.revision_pending` makes the window visible. A revision with
no approved correction behind it is refused (`NOTHING_TO_REVISE`): an official
statement is not reissued because somebody pressed a button.

**Scope is one student**, and that is provable rather than assumed:
`results_service._compute` reads a single student's marks and nothing else — no
rank, no cohort average, no shared denominator — so one child's corrected mark
cannot alter another's figures. Versioning a whole cohort would retire
thirty-nine correct published results to say nothing new about any of them.

**Revision and publication stay separate.** `revise_result` recomputes into
version N+1 with `published_at = NULL`; `publish_revision` is what tells the
audience. Recomputing a number and issuing it are two decisions, and a school
may want to look before it goes out. The examination's own lifecycle does not
move — it is already `published`, and a second transition would be a second
state machine for the same fact. There is still no unpublish.

**"Current" is not "official".** Between revision and its publication, the
current version is a working figure nobody has been told about while the
school's word is the older published one. `results_service.current_result`
answers the first question and `revision_service.official_result` the second;
anything showing a result to a parent asks the latter.

Each version freezes what *it* saw, so version 1 keeps the band it resolved
against and version 2 resolves afresh — the same rule applied twice, not a
different one.

Authority is `examination.publish` for both revising and publishing the
revision, which the catalogue already names: *"Publish and revise examination
results"*. Correcting the mark still needs `assessment.update` plus ADR-014
standing, so a teacher who may correct does not thereby reissue the school's
word, and a publisher does not thereby gain mark-correction authority.

Revision inherits every calculation guard by construction, because it calls the
same `compute_result`: a weighted paper still refuses, a non-finite mark still
refuses.

## No event for calculation

Calculation emits nothing. `business-events.md` has `ResultsPublished` and
`ResultsRevised`, both of which belong to publication. A recalculation is an
internal derivation a school neither asks for nor is told about, and an event
per run would be noise on the timeline that matters.

---

# Consequences

## What this makes easy

- Reconstructing exactly how any result was reached, from the snapshot alone.
- Changing grading configuration without touching a single computed result.
- Adding weighted aggregation later without revisiting the status rules.

## What this costs

A school that has set `weight` on its papers cannot calculate at all until
weighted aggregation is built. That is deliberate: the alternative was a wrong
number with no indication it was wrong.

A locked paper with no mark for a student is not that student's paper. Paper
applicability reuses `is_eligible` (EX-02A.1) — a closed paper's cohort is its
own register — so `not_yet_entered` can arise only for papers still open.
Nothing recorded who was *expected* to sit a closed paper (debt 51), and reading
today's enrollment to find out is the bug EX-02A.1 fixed.

## What a reader must not conclude

That `component_label` groups anything. In EX-03A it is **descriptive only**:
theory and practical are two papers that each contribute independently, exactly
like two subjects. Subject-level aggregation is not modelled and was not
invented here.

---

# Alternatives considered

**Treat a missing mark as absent** — rejected: fails a student for a teacher's
unfinished work, and erases the distinction EX-02A built.

**Treat exempted as zero, or as present-with-full-marks** — rejected: the first
penalises an excused student, the second inflates them. Removing the paper is
the only treatment that does neither.

**Malpractice forces failure** — rejected as an invention. It is a real policy
at some boards, but no repository evidence establishes it, and it is expressible
later as a scheme-level rule without changing this model.

**Ignore `weight` for now** — rejected: silently produces an unweighted result
for a school that configured a weighted one.

**Grade on the unrounded percentage** — rejected: the printed number and the
graded number must be the same number.

**Version every recalculation** — rejected: versions would stop meaning
"something the school said".

---

# Related

- ADR-016 — examination grain (applicability derived from papers)
- ADR-018 — frozen snapshots, versioned, never edited
- EX-02A.1 — historical cohort; `is_eligible` is the applicability rule
- debt 51 — the expected-but-unmarked cohort after locking
- debt 52 — weighted aggregation
- debt 53 — grading band integrity
