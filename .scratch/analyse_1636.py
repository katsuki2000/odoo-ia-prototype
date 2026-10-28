import json
import re
import statistics
import unicodedata
from collections import defaultdict

NEW_FACTS = {
    'FACT-01': ['25 du mois'],
    'FACT-02': ['30 minutes', '4 heures'],
    'FACT-03': ['-u miro_facturation', '--stop-after-init', '--log-level=warn'],
    'FACT-04': ['39 600 000', 'MADAGASCAR INFORMATIQUE SERVICES'],
    'FACT-05': ['150 000'],
    'FACT-06': ['12 caractères', '5 tentatives'],
    'FACT-07': ['rapprochement', 'Comptable Trésorerie'],
    'FACT-08': ['10%', 'Directeur Commercial'],
    'LIST-01': ['NIF', 'Numéro Statistique', 'RIB', 'Conditions Générales de Vente', 'anti-corruption'],
    'LIST-02': ['sudo systemctl stop odoo', 'git checkout HEAD~1', 'pg_restore', 'sudo systemctl start odoo'],
    'LIST-03': ['P1', 'P2', 'P3', 'P4', '30 minutes', '2 heures', '4 heures', '24 heures'],
    'LIST-04': ['division par zéro', 'ensure_one', 'Many2one', '.get()', 'elif', 'except', 'with_context'],
    'TABLE-01': ['DAF', '48 heures'],
    'TABLE-02': ['Core i7', '27', 'Casque', '36 mois'],
    'MULTI-01': ['Directeur Général'],
    'MULTI-02': ['VPN', 'équipements personnels', '2FA', '6h', '30 minutes'],
    'MULTI-03': ['33 000 000', '5 000 000', 'Directeur Général', '72 heures', 'Direction des Achats'],
    'MULTI-04': ['24h', '2%', 'bloquée'],
}


def fold(text):
    return ''.join(ch for ch in unicodedata.normalize('NFD', text) if unicodedata.category(ch) != 'Mn')


def normalize(text):
    return re.sub(r'[\s*`]+', '', fold(text.casefold()).replace('’', "'"))


def contains(folded, fact):
    needle = re.escape(normalize(fact))
    before = r'(?<!\d)' if needle[0].isdigit() else ''
    after = r'(?!\d)' if needle[-1].isdigit() else ''
    return re.search(before + needle + after, folded) is not None


questions = {q['id']: q for q in json.load(open('tests/rag_eval_questions.json'))['questions']}
contexts = json.load(open('captures/rag_eval_contexts.json'))
runs = [json.loads(l) for l in open('captures/rag_model_eval.jsonl') if l.strip()]

for qid, facts in NEW_FACTS.items():
    reference = normalize(questions[qid]['reference'])
    context = normalize(' '.join(c['document'] for c in contexts[qid]['chunks']))
    for fact in facts:
        flags = ('ref' if contains(reference, fact) else 'NOREF', 'ctx' if contains(context, fact) else 'NOCTX')
        if 'NOREF' in flags or 'NOCTX' in flags:
            print(qid, repr(fact), flags)

per_model_old, per_model_new = defaultdict(list), defaultdict(list)
per_fact = defaultdict(list)
for run in runs:
    qid = run['question_id']
    if run['error'] or not run['answerable']:
        continue
    folded = normalize(run['answer'])
    hits = [contains(folded, f) for f in NEW_FACTS[qid]]
    per_model_old[run['model']].append(run['fact_recall'])
    per_model_new[run['model']].append(sum(hits) / len(hits))
    for fact, hit in zip(NEW_FACTS[qid], hits):
        per_fact[(qid, fact)].append(hit)

print()
for model in per_model_old:
    print(f'{model:<22} old {statistics.mean(per_model_old[model]):.0%}  new {statistics.mean(per_model_new[model]):.0%}')
print()
for (qid, fact), hits in per_fact.items():
    if sum(hits) / len(hits) < 0.5:
        print(f'{qid} {fact!r}: {sum(hits)}/{len(hits)}')
