import ast
from code_intelligence.rules.security import SecurityLockASTVisitor

src = '''
class PurchaseOrder(models.Model):
    _name = "purchase.order"

    @api.ondelete(at_uninstall=False)
    def _unlink_if_cancelled(self):
        for order in self:
            if not order.state == 'cancel':
                raise UserError(_('In order to delete a purchase order, you must cancel it first.'))
'''
tree = ast.parse(src)
v = SecurityLockASTVisitor('dummy.py')
v.visit(tree)
print("exception_messages:", v.exception_messages)
print("exception_conditions:", v.exception_conditions)
print("exception_methods:", v.exception_methods)
