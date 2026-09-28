# Synthesis bench on frozen evidence

Scoring is deterministic and heuristic (identifier overlap against the frozen prompt); verbatim answers in the JSON report remain the reference for human review.

| Model | Valid / total | Identifier recall | Unsupported ids | Think leak | Degenerate | Errors | Mean s |
|---|---|---|---|---|---|---|---|
| ollama:gpt-oss:20b | 9 / 9 | 0.25 | 0 | 0 | 0 | 0 | 17.91 |

## Per question

| Case | Model | Sample | Recall | Unsupported identifiers |
|---|---|---|---|---|
| PUR-Q1 | ollama:gpt-oss:20b | 1 | 0.0 | - |
| PUR-Q1 | ollama:gpt-oss:20b | 2 | 0.0 | - |
| PUR-Q1 | ollama:gpt-oss:20b | 3 | 0.0 | - |
| PUR-Q5 | ollama:gpt-oss:20b | 1 | 0.0 | - |
| PUR-Q5 | ollama:gpt-oss:20b | 2 | 0.0 | - |
| PUR-Q5 | ollama:gpt-oss:20b | 3 | 0.0 | - |
| STK-Q1 | ollama:gpt-oss:20b | 1 | 0.75 | - |
| STK-Q1 | ollama:gpt-oss:20b | 2 | 0.75 | - |
| STK-Q1 | ollama:gpt-oss:20b | 3 | 0.75 | - |
