#!/usr/bin/env python3
"""
Dump the entire text, structure, headings, tables, and paragraphs of todo/MASTER_ENI.docx
into a comprehensive text file so the agent can read every single section.
"""

import docx

def dump_document(docx_path, out_path):
    doc = docx.Document(docx_path)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"=== FULL DUMP OF {docx_path} ===\n")
        f.write(f"Total Paragraphs: {len(doc.paragraphs)}\n")
        f.write(f"Total Tables: {len(doc.tables)}\n\n")

        # Iterate through all body elements in exact order
        body = doc._body._element
        p_count = 0
        t_count = 0

        for idx, child in enumerate(body):
            tag = child.tag.split('}')[-1]
            if tag == 'p':
                p = docx.text.paragraph.Paragraph(child, doc)
                txt = p.text.strip()
                style = p.style.name if p.style else 'Normal'
                if txt:
                    f.write(f"[P{p_count:04d} | BodyElem {idx:04d} | Style: {style}]\n{txt}\n\n")
                else:
                    # Empty paragraph
                    pass
                p_count += 1
            elif tag == 'tbl':
                t = docx.table.Table(child, doc)
                f.write(f"--- [TABLE {t_count:02d} | BodyElem {idx:04d} | Rows: {len(t.rows)}, Cols: {len(t.columns)}] ---\n")
                for r_idx, row in enumerate(t.rows):
                    row_vals = [c.text.strip().replace('\n', ' ') for c in row.cells]
                    f.write(f"  Row {r_idx:02d}: {' | '.join(row_vals)}\n")
                f.write("--- [END TABLE] ---\n\n")
                t_count += 1

    print(f"Dump complete! Written {p_count} paragraphs and {t_count} tables to {out_path}")

if __name__ == '__main__':
    dump_document('todo/MASTER_ENI.docx', '.scratch/MASTER_ENI_dump.txt')
