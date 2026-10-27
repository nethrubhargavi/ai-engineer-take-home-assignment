# Plan

## What I found before starting
Before writing this plan I ran small probes with no model calls:
1. `parse` returns `[]` for a cut-off reply, a reply with no JSON, and a report with no tests, so a pipeline failure looks like a valid empty result.
2. `to_number` returns `None` for values such as `< 0.5`, `Negative` and `2,29,000`. On the gold labels this drops 19 rows across reports 06, 09 and 11.
3. A strict comparison treats `"13.5"` and `13.5` as different, so a naive eval would penalise the baseline for formatting.

## What I suspect (not yet verified)
In priority order:
1. Silent failures come first, since they corrupt every other measurement.
2. Data loss from the "value must be a number" rule, which conflicts with the schema and the gold labels. I expect the prompt and `to_number` both contribute.
3. Reference ranges the prompt tells the model to invent.
4. Only the first PDF page is read.
5. DPI of 60 (affects PDFs only).
6. Confusion between similar test names (for example MCH and MCHC), and a conflict between the "standard name" rule and printed names such as `FBS`.

## How I'll score
- Pair each extracted row with at most one gold row, using the cleaned test name and the unit to break ties. Ambiguous pairs stay unpaired, and count as one missing and one extra row.
- Compare numeric values by meaning, not by how they're written.
- Report missing rows, extra rows, wrong values, wrong units and wrong names separately, not as one blended score.
- No alias list built from the 8 labeled reports.

## Labels and unlabeled reports
- I won't edit the gold labels. Suspected label errors are listed and reported separately.
- For the 4 unlabeled reports I'll check schema validity, that pipeline failures are logged separately from empty results, and that values can be traced back to the source report. I'll claim no accuracy number for them.

## Not doing
Fine-tuning, a retrieval step or a multi-step agent unless the numbers after the basic fixes show a gap they could close, and changing the gold to raise a score.