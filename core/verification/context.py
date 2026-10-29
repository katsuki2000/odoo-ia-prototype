from dataclasses import dataclass
from functools import cached_property
from typing import Any, FrozenSet, Iterable, Tuple

from core.verification.base_methods import BUILTIN_NAMES
from core.verification.extractors import find_number_tokens


def flatten_numeric_values(value: Any) -> Iterable[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from flatten_numeric_values(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from flatten_numeric_values(item)


@dataclass
class VerificationContext:
    texts: Tuple[str, ...] = ()
    numeric_values: Tuple[float, ...] = ()
    base_methods: FrozenSet[str] = frozenset()

    @cached_property
    def evidence_text(self) -> str:
        return "\n".join(self.texts)

    @cached_property
    def evidence_numbers(self) -> Tuple[float, ...]:
        from_text = (
            reading.value
            for token in find_number_tokens(self.evidence_text)
            for reading in token.readings
        )
        return tuple(self.numeric_values) + tuple(from_text)

    @cached_property
    def native_method_names(self) -> FrozenSet[str]:
        return BUILTIN_NAMES | self.base_methods
