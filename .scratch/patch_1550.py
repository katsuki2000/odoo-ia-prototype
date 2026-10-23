from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def edit(path, pairs):
    file = ROOT / path
    text = file.read_text()
    for old, new in pairs:
        assert text.count(old) == 1, f'{path}: {text.count(old)} matches for {old[:70]!r}'
        text = text.replace(old, new)
    file.write_text(text)


edit('code_intelligence/rules/override_composer.py', [
    ('        is_custom = any(\n'
     '            "/addons/" not in s.get("filepath", "") or "oca" in s.get("filepath", "")\n'
     '            for _, _, s, _ in items\n'
     '        )\n',
     '        is_custom = any("/addons/" not in s.get("filepath", "") for _, _, s, _ in items)\n'),
])

edit('code_intelligence/rules/xml_view_finder.py', [
    ('(0 if ("/addons/" not in x[1] or "oca" in x[1]) else 1, x[0])',
     '(0 if "/addons/" not in x[1] else 1, x[0])'),
])

edit('tests/test_expected_models.py', [
    ('def test_file_is_compatible_with_compare_resolution_pipelines_expected_format():',
     'def test_every_entry_is_a_list_of_model_names():'),
])

edit('tests/expected_models.json', [
    (' Format compatible avec compare_resolution_pipelines.py --expected.', ''),
])

(ROOT / 'scripts/compare_resolution_pipelines.py').unlink()
print('patch OK')
