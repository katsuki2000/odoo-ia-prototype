from odoo import models, fields

class IdeaAi(models.Model):
    _name = 'idea.ai'
    _description = 'Idée d Intégration IA'

    name = fields.Char(string='Titre de l idée', required=True)
    description = fields.Text(string='Description détaillée')
