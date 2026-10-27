import sys
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from xml.sax.saxutils import escape

SRC = 'todo/MASTER_ENI.docx'
FONT = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/>'


def run(text, bold=False, italic=False, size=24, mark=False):
    b = '<w:b/>' if bold else '<w:b w:val="0"/>'
    i = '<w:i/>' if italic else '<w:i w:val="0"/>'
    h = '<w:highlight w:val="yellow"/>' if mark else ''
    return (f'<w:r><w:rPr>{FONT}{b}{i}<w:sz w:val="{size}"/>{h}</w:rPr>'
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')


def para(ppr, runs):
    return parse_xml(f'<w:p {nsdecls("w")}><w:pPr>{ppr}</w:pPr>{runs}</w:p>')


def heading2(text):
    return para('<w:pStyle w:val="Heading2"/><w:spacing w:before="360" w:after="160"/><w:jc w:val="left"/>', run(text, True, size=32))


def heading3(text):
    return para('<w:pStyle w:val="Heading3"/><w:keepNext/><w:spacing w:before="280" w:after="120"/><w:jc w:val="left"/>', run(text, True, size=28))


def heading4(text):
    return para('<w:keepNext/><w:spacing w:before="200" w:after="100"/><w:jc w:val="left"/>', run(text, True, size=24))


def body(text):
    return para('<w:spacing w:before="0" w:after="120" w:line="276" w:lineRule="auto"/><w:jc w:val="both"/>', run(text))


def bullet(lead, text):
    runs = run('• ', True) + (run(lead + ' : ', True) if lead else '') + run(text)
    return para('<w:spacing w:before="40" w:after="80" w:line="276" w:lineRule="auto"/><w:ind w:left="360"/><w:jc w:val="both"/>', runs)


def caption(text):
    return para('<w:keepNext/><w:spacing w:before="120" w:after="120" w:line="276" w:lineRule="auto"/><w:jc w:val="left"/>', run(text, True, size=22))


def placeholder(text):
    return para('<w:spacing w:before="120" w:after="120"/><w:jc w:val="center"/>', run(text, False, True, 22, mark=True))


def figure_caption(text):
    return para('<w:spacing w:before="120" w:after="240" w:line="360" w:lineRule="auto"/><w:jc w:val="center"/>', run(text, False, True))


def cell(text, width, header):
    if header:
        ppr, r = '<w:spacing w:before="80" w:after="80"/><w:jc w:val="center"/>', run(text, True, size=21)
    else:
        ppr, r = '<w:spacing w:before="60" w:after="60"/><w:jc w:val="left"/>', run(text, size=20)
    return f'<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="{width}"/></w:tcPr><w:p><w:pPr>{ppr}</w:pPr>{r}</w:p></w:tc>'


def table(headers, rows, widths):
    grid = ''.join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    head = '<w:tr><w:trPr><w:tblHeader/></w:trPr>' + ''.join(cell(h, w, True) for h, w in zip(headers, widths)) + '</w:tr>'
    lines = ''.join('<w:tr><w:trPr><w:cantSplit/></w:trPr>' + ''.join(cell(c, w, False) for c, w in zip(row, widths)) + '</w:tr>' for row in rows)
    return parse_xml(
        f'<w:tbl {nsdecls("w")}><w:tblPr><w:tblStyle w:val="Table10"/><w:tblW w:type="dxa" w:w="{sum(widths)}"/><w:jc w:val="center"/>'
        f'<w:tblLook w:firstColumn="1" w:firstRow="1" w:lastColumn="0" w:lastRow="0" w:noHBand="0" w:noVBand="1" w:val="04A0"/></w:tblPr>'
        f'<w:tblGrid>{grid}</w:tblGrid>{head}{lines}</w:tbl>')


def spacer():
    return para('<w:spacing w:before="0" w:after="120"/>', '')


from content_ch7_ch10 import BLOCKS, INTRO_PART3

builders = {
    'h2': lambda b: [heading2(b[1])],
    'h3': lambda b: [heading3(b[1])],
    'h4': lambda b: [heading4(b[1])],
    'p': lambda b: [body(b[1])],
    'b': lambda b: [bullet(b[1], b[2])],
    'ph': lambda b: [placeholder(b[1])],
    'fig': lambda b: [placeholder(b[1]), figure_caption(b[2])],
    'table': lambda b: [caption(b[1]), table(b[2], b[3], b[4]), spacer()],
}

doc = Document(SRC)
body_el = doc.element.body
kids = list(body_el)
text = lambda e: ''.join(e.itertext())

if any(text(e).startswith('Chapitre 10. Perspectives') for e in kids):
    sys.exit('Chapters 7 to 10 already present: nothing done.')

part3 = next(i for i, e in enumerate(kids) if text(e).startswith('PARTIE III : R') and 'PARTIE III : R' in text(e)[:20] and i > 600)
conclusion = next(i for i, e in enumerate(kids) if i > part3 and text(e).strip().startswith('CONCLUSION'))
intro = kids[part3 + 1]
assert 'troisi' in text(intro), 'unexpected Part III introduction'
intro.getparent().replace(intro, body(INTRO_PART3))

anchor = kids[conclusion]
for block in BLOCKS:
    for el in builders[block[0]](block):
        anchor.addprevious(el)

doc.save(SRC)
print('inserted', len(BLOCKS), 'blocks before CONCLUSION')
