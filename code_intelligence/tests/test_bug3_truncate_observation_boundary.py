"""Regression tests for safe truncation of Code Intelligence observations."""


from code_intelligence.agent.context import _truncate_observation, _TRUNCATION_MARKER


def _body(result: str) -> str:
    """Strip the trailing truncation marker (if present) to get just the
    text that was actually kept."""
    if result.endswith(_TRUNCATION_MARKER):
        return result[: -len(_TRUNCATION_MARKER)]
    return result


def _assert_never_left_as_partial_token(ident: str, result: str) -> None:
    """Generic 'never partial' check for a whitespace-delimited identifier:
    the last whitespace-delimited token of the kept text must not be a
    strict, non-empty prefix of `ident` -- if `ident` was cut at all, it
    must have been dropped entirely (retreat to the space/newline before
    it), never left dangling half-written."""
    body = _body(result)
    tokens = body.split()
    last_token = tokens[-1] if tokens else ""
    is_dangling_partial = (
        last_token != "" and last_token != ident and ident.startswith(last_token)
    )
    assert not is_dangling_partial, (
        f"identifier left dangling as a partial token: {last_token!r} "
        f"(from {ident!r})"
    )


# ── No-op cases (text already within limit) ──────────────────────────────

def test_no_op_when_text_within_limit():
    text = "Texte court, largement sous la limite."
    result = _truncate_observation(text, 1000)
    assert result == text
    assert not result.endswith(_TRUNCATION_MARKER)


def test_no_op_when_text_exactly_at_limit():
    text = "x" * 50
    assert _truncate_observation(text, 50) == text


# ── San Goku's matrix: real amounts never left as a different, shorter,
#    truncated-but-still-numeric-looking amount ───────────────────────────

def test_5000_never_truncated_to_500():
    """Direct reproduction of the section 500 root cause: a raw slice at
    this exact limit used to cut "5000" down to "500"."""
    text = (
        "Verrou : condition rec.amount_total > 5000 supplementaire, "
        "distincte du groupe requis ci-dessus."
    )
    idx = text.index("5000")
    limit = idx + 3  # would cut right after "500", mid-number
    result = _truncate_observation(text, limit)
    assert "500" not in result
    assert result.endswith(_TRUNCATION_MARKER)


def test_20000_never_truncated_to_2000():
    text = (
        "Chaine relationnelle : rec.total_ht > 20000 declenche "
        "l'escalade vers le module regional."
    )
    idx = text.index("20000")
    limit = idx + 4  # would cut right after "2000", mid-number
    result = _truncate_observation(text, limit)
    assert "2000" not in result
    assert result.endswith(_TRUNCATION_MARKER)


def test_xml_id_never_truncated_mid_identifier():
    ident = "custom_credit_note_approval_regional.rule_avoir_vip"
    text = f"Module concerne : {ident} suite du texte ici, sans rapport."
    idx = text.index(ident)
    limit = idx + 20  # cut mid-identifier
    result = _truncate_observation(text, limit)
    assert ident not in result
    _assert_never_left_as_partial_token(ident, result)


def test_method_name_never_truncated_mid_identifier():
    ident = "action_valider_avoir_client_vip_exceptionnel"
    text = f"Methode surchargee : {ident} plus loin dans le texte ici."
    idx = text.index(ident)
    limit = idx + 15  # cut mid-identifier
    result = _truncate_observation(text, limit)
    assert ident not in result
    _assert_never_left_as_partial_token(ident, result)


# ── Boundary-selection strategy ───────────────────────────────────────────

def test_newline_boundary_preferred_over_earlier_space():
    text = (
        "Ligne complete un.\n"
        "Ligne complete deux avec plusieurs mots ici.\n"
        "Ligne trois tronquee partiellement ici"
    )
    prefix = "Ligne complete un.\nLigne complete deux avec plusieurs mots ici.\n"
    limit = len(prefix) + 10  # a few chars into line three
    result = _truncate_observation(text, limit)
    assert _body(result) == (
        "Ligne complete un.\nLigne complete deux avec plusieurs mots ici."
    )
    assert result.endswith(_TRUNCATION_MARKER)


def test_falls_back_to_raw_cut_when_no_safe_boundary_exists():
    """Documented, accepted trade-off (ci_helpers.py docstring, strategy
    step 3): a single unbroken token longer than `limit`, with no newline
    or space anywhere before the cut, has no safe boundary to retreat to
    -- the raw index cut is kept rather than refusing to truncate at all."""
    text = "x" * 100
    result = _truncate_observation(text, 40)
    assert _body(result) == "x" * 40
    assert result.endswith(_TRUNCATION_MARKER)
