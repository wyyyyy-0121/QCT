# V5.1.2 real-workbook validation

Scope: retrospective Enron localization on all included events; no automatic promotion.

The original strict scorer rejected two events with labels outside the formula ranking. This versioned scope audit preserves all events, gives missing labels zero AP credit in the full-label denominator, and separately reports fully rankable events. Frozen predictions, model sources, and synthetic scoring gates are unchanged.

| Model | Events | MRR | AP, full labels | Hit@1 | Hit@5 | Hit@10 | Candidate cells |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v4 | 30 | 37.74% | 33.14% | 26.67% | 46.67% | 60.00% | 1588 |
| v511 | 30 | 27.79% | 29.11% | 20.00% | 40.00% | 53.33% | 98 |
| v512 | 30 | 18.33% | 19.55% | 10.00% | 26.67% | 40.00% | 11 |

## Fully rankable events

| Model | Events | MRR | AP |
| --- | ---: | ---: | ---: |
| v4 | 28 | 40.28% | 35.26% |
| v511 | 28 | 29.64% | 30.67% |
| v512 | 28 | 19.54% | 20.67% |

## Label scope and limits

- enron_event_04: 18/20 annotated cells are present in the formula ranking; missing coordinates are recorded in result.json.
- enron_event_13: 191/337 annotated cells are present in the formula ranking; missing coordinates are recorded in result.json.

Parser coverage: 14489/15315 formula cells.

Known error locations do not establish correct repair formulas or complete clean-cell truth. Repair precision and false-positive rate are unavailable. Results are retrospective because these workbooks have previously been used in the project.

The v4 and v511 algorithm source files match their historical files. All methods use the common current parsing runtime frozen for this evaluation. V4's shared a1/formula/workbook modules differ from its original release tree; this is not a replay of the complete original V4 environment.
