"""Frozen-evidence synthesis bench: capture the real synthesis prompt once,
then replay it against any model to compare synthesis quality in isolation."""

import json
import statistics
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from langchain_core.messages import HumanMessage

from config.settings import LLM_MODEL
from core.evaluation.synthesis_metrics import SynthesisScore, score_answer
from core.llm.llm_client import get_chat_llm, invoke_with_rate_limit

NO_THINK_MARKER = "/no_think"
SYNTHESIS_MAX_TOKENS = 4096
SYNTHESIS_MODEL_KWARGS = {"frequency_penalty": 0.3, "presence_penalty": 0.2}


@dataclass(frozen=True)
class ModelSpec:
    model: str

    @classmethod
    def parse(cls, raw: str) -> "ModelSpec":
        return cls(model=raw)

    @property
    def label(self) -> str:
        return self.model

    @property
    def supports_thinking_switch(self) -> bool:
        return self.model.lower().startswith("qwen3")


@dataclass
class FrozenCase:
    id: str
    question: str
    synthesis_prompt: str
    reference_answer: str


@dataclass
class SampleResult:
    case_id: str
    model: str
    sample: int
    seconds: float
    answer: str
    score: Optional[SynthesisScore] = None
    error: Optional[str] = None


class SynthesisPromptRecorder:
    """Records every prompt built by the ReAct loop's synthesis step."""

    def __init__(self) -> None:
        self.prompts: List[str] = []

    @property
    def last_prompt(self) -> Optional[str]:
        return self.prompts[-1] if self.prompts else None

    @contextmanager
    def attached(self) -> Iterator["SynthesisPromptRecorder"]:
        import code_intelligence.agent.loop as loop_module

        original = loop_module.build_synthesis_prompt

        def recording(*args, **kwargs):
            prompt = original(*args, **kwargs)
            self.prompts.append(prompt)
            return prompt

        loop_module.build_synthesis_prompt = recording
        try:
            yield self
        finally:
            loop_module.build_synthesis_prompt = original


def save_case(directory: Path, case: FrozenCase) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{case.id}.json"
    path.write_text(json.dumps(asdict(case), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_cases(directory: Path, case_ids: Optional[List[str]] = None) -> List[FrozenCase]:
    cases = [
        FrozenCase(**json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.json"))
    ]
    if case_ids:
        cases = [case for case in cases if case.id in set(case_ids)]
    return cases


def default_model_specs() -> List[ModelSpec]:
    return [ModelSpec.parse(LLM_MODEL)]


def generate_answer(
    spec: ModelSpec,
    prompt: str,
    temperature: float,
    base_url: Optional[str],
    allow_thinking: bool,
) -> str:
    def build_llm():
        return get_chat_llm(
            model=spec.model, base_url=base_url,
            temperature=temperature, max_tokens=SYNTHESIS_MAX_TOKENS,
            model_kwargs=dict(SYNTHESIS_MODEL_KWARGS),
        )

    if spec.supports_thinking_switch and not allow_thinking:
        prompt = f"{prompt}\n\n{NO_THINK_MARKER}"
    response, _ = invoke_with_rate_limit(build_llm(), [HumanMessage(content=prompt)], rebuild_llm=build_llm)
    return response.content


def _summarize_error(error: Exception, limit: int = 300) -> str:
    return " ".join(str(error).split())[:limit]


def replay(
    cases: List[FrozenCase],
    specs: List[ModelSpec],
    samples: int,
    temperature: float,
    base_url: Optional[str],
    allow_thinking: bool,
) -> List[SampleResult]:
    results: List[SampleResult] = []
    for spec in specs:
        for case in cases:
            for index in range(samples):
                started = time.perf_counter()
                try:
                    answer = generate_answer(spec, case.synthesis_prompt, temperature, base_url, allow_thinking)
                except Exception as error:
                    seconds = round(time.perf_counter() - started, 2)
                    results.append(SampleResult(case.id, spec.label, index + 1, seconds, "", error=_summarize_error(error)))
                    print(f"[{spec.label}] {case.id} sample {index + 1}/{samples}: FAILED after {seconds}s "
                          f"({type(error).__name__}), excluded from the scores")
                    continue
                seconds = round(time.perf_counter() - started, 2)
                score = score_answer(answer, case.synthesis_prompt, case.reference_answer)
                results.append(SampleResult(case.id, spec.label, index + 1, seconds, answer, score))
                print(f"[{spec.label}] {case.id} sample {index + 1}/{samples}: {seconds}s, "
                      f"recall={score.identifier_recall}, unsupported={len(score.unsupported_identifiers)}")
    return results


def summarize(results: List[SampleResult]) -> Dict[str, Dict[str, float]]:
    summary: Dict[str, Dict[str, float]] = {}
    for label in sorted({r.model for r in results}):
        rows = [r for r in results if r.model == label]
        valid = [r for r in rows if r.error is None]
        recalls = [r.score.identifier_recall for r in valid if r.score.identifier_recall is not None]
        summary[label] = {
            "samples": len(rows),
            "valid_samples": len(valid),
            "errors": len(rows) - len(valid),
            "mean_identifier_recall": _mean(recalls, 3),
            "mean_unsupported_identifiers": _mean([len(r.score.unsupported_identifiers) for r in valid], 2),
            "unsupported_claim_rate": _mean([bool(r.score.unsupported_claims) for r in valid], 3),
            "think_leak_rate": _mean([r.score.think_leak for r in valid], 3),
            "degenerate_rate": _mean([r.score.degenerate for r in valid], 3),
            "mean_seconds": _mean([r.seconds for r in valid], 2),
        }
    return summary


def _mean(values: List[float], digits: int) -> float:
    return round(statistics.mean(values), digits) if values else 0.0


def render_markdown(results: List[SampleResult], summary: Dict[str, Dict[str, float]]) -> str:
    lines = [
        "# Synthesis bench on frozen evidence\n",
        "Scoring is deterministic and heuristic (identifier overlap and rule-based unsupported claims against the frozen prompt); "
        "verbatim answers in the JSON report remain the reference for human review.\n",
        "| Model | Valid / total | Identifier recall | Unsupported ids | Unsupported claims | Think leak | Degenerate | Errors | Mean s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for label, stats in summary.items():
        lines.append(
            f"| {label} | {stats['valid_samples']} / {stats['samples']} | {stats['mean_identifier_recall']} | "
            f"{stats['mean_unsupported_identifiers']} | {stats['unsupported_claim_rate']} | {stats['think_leak_rate']} | "
            f"{stats['degenerate_rate']} | {stats['errors']} | {stats['mean_seconds']} |"
        )
    lines += ["", "## Per question", "", "| Case | Model | Sample | Recall | Unsupported identifiers | Unsupported claims |", "|---|---|---|---|---|---|"]
    for r in results:
        if r.error is not None:
            lines.append(f"| {r.case_id} | {r.model} | {r.sample} | error | {r.error[:80]} | - |")
            continue
        unsupported = ", ".join(r.score.unsupported_identifiers[:8]) or "-"
        claims = ", ".join(r.score.unsupported_claims) or "-"
        lines.append(f"| {r.case_id} | {r.model} | {r.sample} | {r.score.identifier_recall} | {unsupported} | {claims} |")
    return "\n".join(lines) + "\n"
