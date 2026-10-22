fr = env(context=dict(env.context, lang='fr_FR'))
print("menu     :", env.ref('miro_ai.menu_miro_ai_log').with_context(lang='fr_FR').name)
print("menu cfg :", env.ref('miro_ai.menu_miro_ai_settings_action').with_context(lang='fr_FR').name)
print("groupe   :", env.ref('miro_ai.group_miro_ai_admin').with_context(lang='fr_FR').name)
print("categorie:", env.ref('miro_ai.module_category_miro_ai').with_context(lang='fr_FR').name)
print("action   :", env.ref('miro_ai.action_miro_ai_log').with_context(lang='fr_FR').name)
f = fr['ir.model.fields']._get('miro.ai.log', 'response_time_ms')
print("champ    :", f.field_description, "|", f.help)
print("selection:", fr['miro.ai.log'].fields_get(['state'])['state']['selection'])
arch = fr['miro.ai.log'].get_view(view_type='search')['arch']
print("search   :", all(w in arch for w in ("Succès", "Erreurs", "Aujourd'hui", "Regrouper par")))
form = fr['miro.ai.log'].get_view(view_type='form')['arch']
print("form     :", "Question &amp; Réponse" in form or "Question & Réponse" in form)
s = fr['miro.ai.settings'].create({'api_token': 'court'})
try:
    s.get_signing_secret()
except Exception as e:
    print("UserError:", e.args[0])
en = env(context=dict(env.context, lang='en_US'))
s2 = en['miro.ai.settings'].browse(s.id)
try:
    s2.get_signing_secret()
except Exception as e:
    print("UserError en:", e.args[0])
env.cr.rollback()
