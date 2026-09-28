# Synthesis bench on frozen evidence

Scoring is deterministic and heuristic (identifier overlap against the frozen prompt); verbatim answers in the JSON report remain the reference for human review.

| Model | Valid / total | Identifier recall | Unsupported ids | Think leak | Degenerate | Errors | Mean s |
|---|---|---|---|---|---|---|---|
| ollama:qwen3:14b | 9 / 9 | 0.287 | 0 | 0 | 0 | 0 | 53.34 |

## Per question

| Case | Model | Sample | Recall | Unsupported identifiers |
|---|---|---|---|---|
| PUR-Q1 | ollama:qwen3:14b | 1 | 0.0 | - |
| PUR-Q1 | ollama:qwen3:14b | 2 | 0.16666666666666666 | - |
| PUR-Q1 | ollama:qwen3:14b | 3 | 0.16666666666666666 | - |
| PUR-Q5 | ollama:qwen3:14b | 1 | 0.0 | - |
| PUR-Q5 | ollama:qwen3:14b | 2 | 0.0 | - |
| PUR-Q5 | ollama:qwen3:14b | 3 | 0.0 | - |
| STK-Q1 | ollama:qwen3:14b | 1 | 0.75 | - |
| STK-Q1 | ollama:qwen3:14b | 2 | 0.75 | - |
| STK-Q1 | ollama:qwen3:14b | 3 | 0.75 | - |
