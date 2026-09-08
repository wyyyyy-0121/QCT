# Protected-data access deviation record

Date: 2026-08-31
Status: closed; protected evaluation remains locked

While locating public model-source directories, a broad `find` command rooted above
the FormulaGuard repository emitted the protected directory path and two immediate
child-directory entries. The command did not enumerate files below those entries and
did not read, open, copy, parse, hash, count, or score any protected file. No content,
label, workbook name, case identity, schema value, or archive metadata entered a
model, feature, result, or committed artifact.

This was still a deviation from the stricter preregistered rule that prohibited any
directory enumeration before candidate lock. It is recorded rather than silently
described as zero enumeration. The two child names are intentionally not repeated in
this record. They convey no task or label information, so the protected package
remains unused and eligible for the eventual one-shot evaluation.

Corrective action:

1. all subsequent discovery commands are rooted inside `/home/ayaka/QCT`;
2. the protected path is excluded from acquisition, overlap, cache, and source scans;
3. no further access is allowed until the committed FCRL protected-data condition is
   satisfied;
4. future status records distinguish zero content access from this one path-level
   enumeration deviation.
