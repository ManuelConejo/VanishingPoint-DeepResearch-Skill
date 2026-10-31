# o/lib@4f2b9c0d — retry helper

## Main Analysis

### Finding 1 — Retry with exponential wait (WATCH)

**Y side.** The helper waits "base * 2**n seconds between attempts" [1]. It gives up with "raise RuntimeError('gave up')" [1]. The text also claims "a sentence that is not in the file" [1]. The wait module starts with "def wait_forever(step)" [2].

**X side.** The seam is the "def call_with_retry(fn)" helper [4].

## Bibliography

[1] o/lib, `src/retry.py:4@4f2b9c0d` (l.4-6 docstring) — https://github.com/o/lib/blob/4f2b9c0d1e3a5b7c9d0e1f2a3b4c5d6e7f8a9b0c/src/retry.py#L4-L6 ; #L11
[2] o/lib, `src/wait.py:40@4f2b9c0d` — https://github.com/o/lib/blob/4f2b9c0d1e3a5b7c9d0e1f2a3b4c5d6e7f8a9b0c/src/wait.py#L40
[3] o/lib, `src/absent.py:1@4f2b9c0d` — https://github.com/o/lib/blob/4f2b9c0d1e3a5b7c9d0e1f2a3b4c5d6e7f8a9b0c/src/absent.py#L1
[4] X, `local:tools/x.py:3@0123abcd`
