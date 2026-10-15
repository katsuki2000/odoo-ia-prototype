from fpdf import FPDF
from PIL import Image, ImageDraw
import os

# 1. Creer une image avec du texte (simulation de scan)
img = Image.new('RGB', (800, 1000), color = (255, 255, 255))
d = ImageDraw.Draw(img)

# On dessine du texte simple sur l'image
text = """FACTURE SCANNEE - MIRO KE

Client : Madagascar Tech
Date : 10 Mars 2026
Montant : 1 200 000 Ar

Description :
- 10 licences Odoo
- Prestation de formation (3 jours)

Cette facture a ete numerisee depuis un 
document papier original."""

# On utilise la police par defaut de Pillow
d.text((50, 50), text, fill=(0,0,0))
img.save("document_rag/fake_data/documents/temp_scan.png")

# 2. Creer un PDF et y inserer l'image
pdf = FPDF()
pdf.add_page()
pdf.image("document_rag/fake_data/documents/temp_scan.png", x=10, y=10, w=190)
pdf.output("document_rag/fake_data/documents/facture_scannee.pdf")

# 3. Nettoyer l'image temporaire
os.remove("document_rag/fake_data/documents/temp_scan.png")

print("PDF scanné généré : facture_scannee.pdf")
