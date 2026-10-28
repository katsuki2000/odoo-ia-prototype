import json
import re
from pathlib import Path

PATH = Path('tests/rag_eval_questions.json')

FACTS = {
    'FACT-02': ['30 minutes', '4 heures'],
    'FACT-05': ['150 000'],
    'FACT-06': ['12 caractères', '5 tentatives'],
    'FACT-07': ['rapprochement', 'Comptable Trésorerie'],
    'FACT-08': ['10%', 'Directeur Commercial'],
    'LIST-01': ['NIF', 'Numéro Statistique', 'RIB', 'Conditions Générales de Vente', 'anti-corruption'],
    'LIST-03': ['P1', 'P2', 'P3', 'P4', '30 minutes', '2 heures', '4 heures', '24 heures'],
    'LIST-04': ['division par zéro', 'ensure_one', 'Many2one', '.get()', 'elif', 'except', 'with_context'],
    'TABLE-01': ['DAF', '48 heures'],
    'TABLE-02': ['Core i7', '27', 'Casque', '36 mois'],
    'MULTI-01': ['Directeur Général'],
    'MULTI-02': ['VPN', 'équipements personnels', '2FA', '6h', '30 minutes'],
    'MULTI-03': ['33 000 000', '5 000 000', 'Directeur Général', '72 heures', 'Direction des Achats'],
    'MULTI-04': ['24h', '2%', 'bloquée'],
}

OLD_DESCRIPTION = 'every item of `facts` must appear verbatim in the listed source documents.'
NEW_DESCRIPTION = 'every item of `facts` is a key value (number, name or command) taken from the listed source documents that a correct answer states.'

text = PATH.read_text(encoding='utf-8')
assert text.count(OLD_DESCRIPTION) == 1
text = text.replace(OLD_DESCRIPTION, NEW_DESCRIPTION)

for questionId, facts in FACTS.items():
    pattern = re.compile(r'("id": "' + re.escape(questionId) + r'",(?:(?!"id": ).)*?"facts": )\[[^\]]*\]', re.DOTALL)
    assert len(pattern.findall(text)) == 1, questionId
    text = pattern.sub(lambda match: match.group(1) + json.dumps(facts, ensure_ascii=False), text)

PATH.write_text(text, encoding='utf-8')
questions = {item['id']: item for item in json.loads(text)['questions']}
assert all(questions[questionId]['facts'] == facts for questionId, facts in FACTS.items())
assert len(questions) == 20
print('ok')
