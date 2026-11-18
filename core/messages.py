"""Fixed user-facing answers returned when no model-written answer is available. English only."""

NO_SOURCE_ANSWER = "I have no reliable source to answer this question."
NO_DATA_ANSWER = "I have no data available to answer this question."
NO_READ_ANSWER = (
    "I could not read the data needed to answer: access was denied or failed. "
    "Specify the subject, status or period, or rephrase the question."
)
INCOMPLETE_ANSWER = "I could not produce a complete answer from the available observations."
GENERATION_ERROR_ANSWER = "An error occurred while generating the answer. Please try again."
LLM_UNAVAILABLE_ANSWER = (
    "The language model is temporarily unreachable, so I cannot answer right now. "
    "Try again in a moment; if the problem persists, contact the administrator."
)
RETIREMENT_NOTICE = "[DETERMINISTIC VERIFICATION] Claim(s) removed for lack of evidence in this turn's data: "
