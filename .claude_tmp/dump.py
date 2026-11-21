import sys, zipfile
from lxml import etree
W="http://schemas.openxmlformats.org/wordprocessingml/2006/main"; ns={"w":W}; q=lambda t:"{%s}%s"%(W,t)
def ptext(p):
    o=[]
    for el in p.iter():
        if el.tag==q("t"): o.append(el.text or "")
        elif el.tag==q("instrText"): o.append("{"+(el.text or "").strip()+"}")
        elif el.tag in (q("drawing"),q("pict")): o.append("[IMG]")
    return "".join(o)
z=zipfile.ZipFile(sys.argv[1]); body=etree.fromstring(z.read("word/document.xml")).find("w:body",ns)
out=open(sys.argv[2],"w")
for el in body:
    if el.tag==q("p"):
        st=el.find("w:pPr/w:pStyle",ns); st=st.get(q("val")) if st is not None else ""
        out.write("P[%s]\t%s\n"%(st,ptext(el)))
    elif el.tag==q("tbl"):
        out.write("TBL\n")
        for tr in el.findall("w:tr",ns):
            out.write("\t"+" | ".join(" ".join(ptext(p) for p in tc.findall(".//w:p",ns)) for tc in tr.findall("w:tc",ns))+"\n")
