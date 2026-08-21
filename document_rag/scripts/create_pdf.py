# document_rag/fake_data/documents/create_pdf.py
from fpdf import FPDF

pdf = FPDF()
pdf.add_page()
pdf.set_font("Helvetica", "B", 16)
pdf.cell(0, 10, "Manuel Odoo 17 - Facturation", ln=True)

pdf.set_font("Helvetica", "B", 13)
pdf.cell(0, 10, "1. Creer une facture client", ln=True)
pdf.set_font("Helvetica", size=11)
pdf.multi_cell(0, 8,
    "Aller dans Comptabilite > Clients > Factures > Nouveau.\n"
    "Selectionner le client, ajouter les lignes de produits,\n"
    "puis cliquer sur Confirmer pour valider la facture.\n"
    "Une facture confirmee passe en statut Publie et\n"
    "ne peut plus etre modifiee directement."
)

pdf.set_font("Helvetica", "B", 13)
pdf.cell(0, 10, "2. Envoyer une facture par email", ln=True)
pdf.set_font("Helvetica", size=11)
pdf.multi_cell(0, 8,
    "Depuis la facture confirmee, cliquer sur Envoyer et Imprimer.\n"
    "Odoo genere automatiquement un email avec le PDF en piece jointe.\n"
    "Le modele d'email est configurable dans Configuration > Modeles d'email."
)

pdf.set_font("Helvetica", "B", 13)
pdf.cell(0, 10, "3. Creer un avoir (note de credit)", ln=True)
pdf.set_font("Helvetica", size=11)
pdf.multi_cell(0, 8,
    "Un avoir annule partiellement ou totalement une facture.\n"
    "Depuis la facture, cliquer sur Avoir.\n"
    "Choisir la date et le journal, puis confirmer.\n"
    "L'avoir doit etre approuve par le Directeur General selon\n"
    "la politique interne de MIRO KE."
)

pdf.set_font("Helvetica", "B", 13)
pdf.cell(0, 10, "4. Relances automatiques", ln=True)
pdf.set_font("Helvetica", size=11)
pdf.multi_cell(0, 8,
    "Odoo peut envoyer des relances automatiques aux clients\n"
    "ayant des factures en retard.\n"
    "Configurable dans Comptabilite > Configuration > Niveaux de relance.\n"
    "3 niveaux disponibles : rappel doux, rappel ferme, mise en demeure."
)

pdf.output("document_rag/fake_data/documents/manuel_facturation.pdf")
print("PDF cree avec succes !")