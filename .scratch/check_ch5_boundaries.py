#!/usr/bin/env python3
"""
Inspect the exact boundaries for moving Chapter 5 in todo/MASTER_ENI.docx.
"""
import docx

doc = docx.Document('todo/MASTER_ENI.docx')
body = doc._body._element

for idx, child in enumerate(body):
    tag = child.tag.split('}')[-1]
    if tag == 'p':
        p = docx.text.paragraph.Paragraph(child, doc)
        t = p.text.strip()
        if any(k in t for k in ['Chapitre 4', 'Tableau 15', 'Chapitre 5', 'Contexte Volume', '5.1. Désignation', '5.12. Diagramme', 'CONCLUSION']):
            print(f'BodyElem {idx:04d} [{p.style.name}]: {t[:70]}')

