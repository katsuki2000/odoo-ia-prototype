"""
code_intelligence/tests/test_bloc_b1_evidence_analyze_security_locks.py

B1 (todo/contexte.txt section 452+, tool 7/24, 2/4 Analyse CI): unit tests
for the structured Evidence produced by analyze_python_security_locks() via
_build_security_lock_evidence(). Complements the pre-existing behavioral
tests for this module (untouched here) with dedicated coverage of the new
`evidence` field: 4 categories always asserted explicitly (positive or
negative), confidence per fact (HIGH for hardcoded_logins/exception_messages
/required_groups, LOW only for a positive dynamic_dispatch finding, HIGH
when explicitly absent), scope discipline (no lineno=0, no method="",
no artificial empty scope), and evidence_id determinism.
"""

import textwrap

from code_intelligence.security import analyze_python_security_locks


class TestSecurityLockEvidenceEmptyCode:
    """No code at all -- still 4 explicit negative facts, not an empty list."""

    def test_count_and_confidence(self):
        analysis = analyze_python_security_locks("", "f.py")
        assert len(analysis.evidence) == 4
        assert all(e.confidence == "HIGH" for e in analysis.evidence)

    def test_all_four_categories_negative(self):
        analysis = analyze_python_security_locks("   ", "f.py")
        sources = {e.source for e in analysis.evidence}
        assert sources == {
            "security_lock:f.py:hardcoded_logins",
            "security_lock:f.py:exception",
            "security_lock:f.py:group",
            "security_lock:f.py:dynamic_dispatch",
        }
        for e in analysis.evidence:
            assert e.value is None
            assert e.scope == {}


class TestSecurityLockEvidenceCleanCode:
    """Code with no security-relevant pattern -- 4 explicit negative facts."""

    def test_clean_code_four_negative_facts(self):
        code = "class Model(models.Model):\n    def foo(self):\n        return True\n"
        analysis = analyze_python_security_locks(code, "clean.py")
        assert len(analysis.evidence) == 4
        assert all(e.confidence == "HIGH" for e in analysis.evidence)
        login_ev = next(e for e in analysis.evidence if e.source == "security_lock:clean.py:hardcoded_logins")
        assert "contains no hardcoded login/email" in login_ev.claim
        assert login_ev.value is None


class TestSecurityLockEvidenceHardcodedLogins:
    def test_positive_value_and_confidence(self):
        code = '_VALIDATEURS_EXCEPTIONNELS = ["admin@corp.com", "root@corp.com"]\n'
        analysis = analyze_python_security_locks(code, "logins.py")
        ev = next(e for e in analysis.evidence if e.source == "security_lock:logins.py:hardcoded_logins")
        assert ev.value == ["admin@corp.com", "root@corp.com"]
        assert ev.confidence == "HIGH"
        assert ev.scope == {}
        assert "admin@corp.com" in ev.claim


class TestSecurityLockEvidenceExceptionMessages:
    def test_one_evidence_per_raise_site_with_lineno_scope(self):
        code = textwrap.dedent("""\
            def action_validate(self):
                if self.montant > 10000:
                    raise ValidationError("Montant trop eleve")
                raise UserError("Acces refuse")
        """)
        analysis = analyze_python_security_locks(code, "exc.py")
        exc_evs = [e for e in analysis.evidence if e.source.startswith("security_lock:exc.py:exception:")]
        assert len(exc_evs) == 2
        assert all(e.confidence == "HIGH" for e in exc_evs)
        for e in exc_evs:
            assert "lineno" in e.scope
            assert e.scope["lineno"] != 0
        montant_ev = next(e for e in exc_evs if e.value == "Montant trop eleve")
        assert "condition:" in montant_ev.claim

    def test_negative_explicit_when_no_raise(self):
        code = "def foo(self):\n    return True\n"
        analysis = analyze_python_security_locks(code, "noexc.py")
        exc_ev = next(e for e in analysis.evidence if e.source == "security_lock:noexc.py:exception")
        assert exc_ev.value is None
        assert "raises no UserError/ValidationError" in exc_ev.claim
        assert exc_ev.confidence == "HIGH"

    def test_regex_fallback_path_has_no_lineno_in_scope(self):
        # Deliberately unparsable module (syntax error) forces the regex
        # fallback path, where exception_linenos stays 0 -- scope must NOT
        # contain a lineno=0 placeholder.
        code = 'raise ValidationError("Erreur de syntaxe volontaire"\n'
        analysis = analyze_python_security_locks(code, "fallback.py")
        exc_evs = [e for e in analysis.evidence if e.source.startswith("security_lock:fallback.py:exception")]
        assert len(exc_evs) >= 1
        for e in exc_evs:
            if e.value is not None:
                assert "lineno" not in e.scope


class TestSecurityLockEvidenceRequiredGroups:
    def test_positive_with_method_and_lineno_scope(self):
        code = textwrap.dedent("""\
            class Model(models.Model):
                def action_post(self):
                    if not self.env.user.has_group('base.group_system'):
                        raise UserError("Acces refuse")
        """)
        analysis = analyze_python_security_locks(code, "grp.py")
        grp_ev = next(e for e in analysis.evidence if e.source == "security_lock:grp.py:group:base.group_system")
        assert grp_ev.value == "base.group_system"
        assert grp_ev.confidence == "HIGH"
        assert grp_ev.scope["method"] == "action_post"
        assert grp_ev.scope["lineno"] != 0
        assert "action_post" in grp_ev.claim

    def test_negative_explicit(self):
        code = "def foo(self):\n    return True\n"
        analysis = analyze_python_security_locks(code, "nogrp.py")
        grp_ev = next(e for e in analysis.evidence if e.source == "security_lock:nogrp.py:group")
        assert grp_ev.value is None
        assert "contains no has_group() requirement" in grp_ev.claim

    def test_module_level_has_group_omits_method_key(self):
        code = "if env.user.has_group('base.group_system'):\n    pass\n"
        analysis = analyze_python_security_locks(code, "modlevel.py")
        grp_ev = next(e for e in analysis.evidence if e.source == "security_lock:modlevel.py:group:base.group_system")
        assert "method" not in grp_ev.scope


class TestSecurityLockEvidenceDynamicDispatch:
    def test_positive_is_low_confidence(self):
        code = "x = getattr(self, name)\ny = eval(expr)\n"
        analysis = analyze_python_security_locks(code, "dyn.py")
        dd_evs = [
            e for e in analysis.evidence
            if e.source.startswith("security_lock:dyn.py:dynamic_dispatch:")
        ]
        assert len(dd_evs) == 2
        patterns = {e.value for e in dd_evs}
        assert patterns == {"getattr", "eval"}
        for e in dd_evs:
            assert e.confidence == "LOW"
            assert "not statically classifiable" in e.claim

    def test_negative_is_high_confidence(self):
        code = "def foo(self):\n    return True\n"
        analysis = analyze_python_security_locks(code, "nodyn.py")
        dd_ev = next(e for e in analysis.evidence if e.source == "security_lock:nodyn.py:dynamic_dispatch")
        assert dd_ev.value is None
        assert dd_ev.confidence == "HIGH"
        assert "uses no dynamic dispatch" in dd_ev.claim


class TestSecurityLockEvidenceScopeAndDeterminism:
    def test_no_empty_placeholder_leaks(self):
        """No lineno=0 and no method='' ever appear in any scope dict."""
        code = textwrap.dedent("""\
            _VALIDATEURS_EXCEPTIONNELS = ["admin@corp.com"]

            class Model(models.Model):
                def action_validate(self):
                    if self.env.user.has_group('base.group_system'):
                        raise UserError("Acces refuse")
                    x = getattr(self, "dynamic")
        """)
        analysis = analyze_python_security_locks(code, "scope.py")
        for e in analysis.evidence:
            assert e.scope.get("lineno") != 0
            assert e.scope.get("method") != ""

    def test_evidence_id_deterministic(self):
        code = textwrap.dedent("""\
            class Model(models.Model):
                def action_validate(self):
                    if self.env.user.has_group('base.group_system'):
                        raise UserError("Acces refuse")
        """)
        a1 = analyze_python_security_locks(code, "det.py")
        a2 = analyze_python_security_locks(code, "det.py")
        ids1 = sorted(e.evidence_id for e in a1.evidence)
        ids2 = sorted(e.evidence_id for e in a2.evidence)
        assert ids1 == ids2


class TestSecurityLockEvidenceFullAdversarial:
    """Mixed code hitting all 4 categories at once (3 positive, 1 negative
    would be the case if exceptions were absent -- here all 4 are positive
    except none omitted): verifies count, confidence split, and that the
    pre-existing behavioral fields (hardcoded_logins, confidence='low' on
    the dataclass itself, etc.) stay untouched by this change."""

    def test_all_four_positive_shape(self):
        code = textwrap.dedent("""\
            _VALIDATEURS_EXCEPTIONNELS = ["admin@corp.com", "root@corp.com"]

            class Model(models.Model):
                def action_validate(self):
                    if self.env.user.login in self._VALIDATEURS_EXCEPTIONNELS:
                        email_ok = True
                    else:
                        email_ok = False
                    if self.montant > 10000 and not email_ok:
                        raise ValidationError("Validation requise pour montant eleve")
                    if not self.env.user.has_group('base.group_system'):
                        raise UserError("Acces refuse")
                    method_name = getattr(self, "dynamic_method")
                    return method_name()
        """)
        analysis = analyze_python_security_locks(code, "adversarial.py")

        # Dataclass-level confidence field untouched by this change
        assert analysis.confidence == "low"

        # 1 hardcoded_logins + 2 exceptions + 1 group + 1 dynamic_dispatch = 5
        assert len(analysis.evidence) == 5

        login_ev = next(e for e in analysis.evidence if "hardcoded_logins" in e.source)
        assert login_ev.confidence == "HIGH"
        assert login_ev.value == ["admin@corp.com", "root@corp.com"]

        exc_evs = [e for e in analysis.evidence if ":exception:" in e.source]
        assert len(exc_evs) == 2
        assert all(e.confidence == "HIGH" for e in exc_evs)

        grp_ev = next(e for e in analysis.evidence if ":group:" in e.source)
        assert grp_ev.confidence == "HIGH"
        assert grp_ev.scope["method"] == "action_validate"

        dd_ev = next(e for e in analysis.evidence if "dynamic_dispatch:getattr" in e.source)
        assert dd_ev.confidence == "LOW"
