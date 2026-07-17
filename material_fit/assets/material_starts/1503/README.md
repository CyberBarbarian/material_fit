# 1503 Crocodile Material Registry

This directory records the two materials supplied with the 1503 / deep
crocodile asset bundle. The complete local renderer payload lives under
`artifacts/crocodile_1503_validation/` and is intentionally excluded from Git.

## Original Start

```text
original/1503_test.lmat
sha256: 01b937841d58a253ffc3ddf8425073dd59e7782895c06af5078d0787d2959eb7
role: untouched original continuous and discrete material state; maintained optimization start
```

## Human-Adjusted Reference

```text
human_adjusted/1503_body.lmat
sha256: 47babf783308c5329545d152df0dcf151b8e3e2d05a50596d40fa1b493b74e2c
role: human-adjusted finished appearance; PNG-target generation and offline evaluation only
```

Maintained optimizers must not read `1503_body.lmat`, its parameters, or its
hard state as a teacher direction. Stage 1 may render it to target PNGs before
the optimizer starts, following the same boundary used for fish and turtle.
