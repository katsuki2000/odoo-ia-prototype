"""Section 1625: extend strip_source_aliases (bare alias forms) + tests."""
p = "document_rag/generate_helpers.py"
c = open(p, encoding="utf-8").read()

anchor = '''IGNORECASE | re.MULTILINE),
]
'''
assert c.count(anchor) == 1, c.count(anchor)
new_patterns = '''IGNORECASE | re.MULTILINE),
    # (S3), (voir S1), (cf. S1, S2)
    re.compile(rf"[ \\t]*\\(\\s*(?:voir|cf\\.?|see)?\\s*{_ALIAS_LIST}\\s*\\)", re.IGNORECASE),
    # bold label closing a quote: " - **Source S4**"
    re.compile(rf"[ \\t]*(?:[\u2014\u2013-][ \\t]*)?\\*\\*\\s*(?:sources?\\s+)?{_ALIAS}\\s*\\*\\*", re.IGNORECASE),
    # reference lines: "- S3 : ...", "Source S1 : Titre"
    re.compile(rf"\\b(?:[Ss]ources?[ \\t]+)?{_ALIAS}[ \\t]*:[ \\t]*"),
    # noun followed by an alias: "la source S2", "le document S1" -> keep the noun
    re.compile(rf"\\b([Ss]ources?|[Dd]ocuments?)[ \\t]+{_ALIAS}\\b"),
    # "page 1 de S1"
    re.compile(rf"(?<=\\d)[ \\t]+de[ \\t]+{_ALIAS}\\b"),
]
'''
c = c.replace(anchor, new_patterns)

old_loop = '            text = pattern.sub("", text)\n'
assert c.count(old_loop) == 1
c = c.replace(old_loop, '            text = pattern.sub(lambda m: m.group(1) if m.re.groups else "", text)\n')
open(p, "w", encoding="utf-8").write(c)

t = "tests/test_strip_source_aliases.py"
s = open(t, encoding="utf-8").read()
assert "test_bare_alias_forms_are_removed" not in s
s += '''

@pytest.mark.parametrize("raw, expected", [
    ("Un montant de 33 000 000 Ar (voir S1). Selon la procédure (S3), ce montant.",
     "Un montant de 33 000 000 Ar. Selon la procédure, ce montant."),
    ("Politique définie dans la source S2.", "Politique définie dans la source."),
    ("Le document S1 indique que oui.", "Le document indique que oui."),
    ("Comme indiqué en page 1 de S1 (33 000 Ar).", "Comme indiqué en page 1 (33 000 Ar)."),
    ("- S3 : texte cité", "- texte cité"),
    ("« Texte. » — **Source S4**", "« Texte. »"),
])
def test_bare_alias_forms_are_removed(raw, expected):
    assert strip_source_aliases(raw) == expected


def test_bare_alias_forms_untouched_in_code_blocks():
    text = "Avant.\\n```\\nvoir (S1) et la source S2\\n```\\nAprès."
    assert strip_source_aliases(text) == text
'''
open(t, "w", encoding="utf-8").write(s)
print("patched")
