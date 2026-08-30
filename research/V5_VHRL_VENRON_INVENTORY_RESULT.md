# FormulaGuard VHRL VEnron inventory result

Date: 2026-08-31
Protocol: `formulaguard_vhrl_venron_inventory_v0`
Implementation commit: `d484a25e4491eb7002c950881f999091fba723af`
Status: archive layout gate passed; no workbook content read

## Result

- pinned archive SHA-256:
  `15f1b134157e65ea68f7e262a73b1571fd9f3f5e1256ab3aa52bfdea87628d98`;
- inventory receipt SHA-256:
  `9ccaf22bec80f276d5715cbaf1225fff7f065b83daea399ff81b68799835c9aa`;
- member manifest SHA-256:
  `f5360f41ec81a5f785fd8d93d949626ea5c8850e0353311ce652c58c23beb8ad`;
- 7,658 archive members at maximum path depth 3;
- 7,295 `.xls` members and one `readme.txt`;
- one `.xls` is `VEnron1.0/Version/FileOrder.xls`;
- the remaining 7,294 workbooks are partitioned into exactly 360 group directories;
- group IDs are unique and continuous from 1 through 360;
- every directory matches `<group_id>_<declared_count>_<name>`, and all 360 declared
  counts equal the observed workbook-member counts.

These aggregate facts match the publisher's claim of 360 evolution groups and 7,294
spreadsheets. They do not yet establish conversion coverage, adjacent-transition
counts, direct formula-edit counts, multi-edit coverage, or regression-proxy labels.

## Read boundary

The inventory enumerated archive member names only. It extracted zero members and
opened zero workbooks. Fault-label inputs and protected-data inputs were both empty.
The detailed member names remain under ignored local results and are not committed.

The receipt key `workbook_extension_counts` contains `.txt: 1` as well as
`.xls: 7295`; its implementation counted all non-directory suffixes, so that key is
misnamed. The independently recorded `workbook_member_count=7295` is correct because
workbook classification used the frozen Excel extension allowlist. This labeling
defect does not alter layout eligibility and is preserved rather than rewriting the
completed receipt.

## Decision

The archive-layout subgate passes. The only next authorized content read is the
single `FileOrder.xls` metadata workbook after its schema intake implementation is
committed and pushed. The 7,294 evolution-group workbooks and all protected data
remain unread.
