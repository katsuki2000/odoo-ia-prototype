# Groq Baseline - Step 1b

Date: 2026-07-08T14:03:25.418820+00:00
Model: `llama-3.1-8b-instant`
Questions: 30
Average latency: 2.63 s/question

## Scores

- Average overall score: 4.18 / 5
- Average French score: 4.90 / 5
- Average source-citing score: 4.87 / 5

| Category | Questions | Average score |
|---|---:|---:|
| code | 5 | 4.60 / 5 |
| doc | 10 | 4.27 / 5 |
| edge_case | 5 | 3.53 / 5 |
| erp | 10 | 4.20 / 5 |

## Tool-Use Validation

- JSON/tool-call parse success: 5/5 (100%)
- Retry/backoff enabled: True
- Burst probe requests: 8
- Burst probe failures after retry: 0

## Decision

Llama 3.1 8B via Groq is adequate for Step 1b validation.
