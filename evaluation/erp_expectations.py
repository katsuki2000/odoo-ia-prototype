"""Expected facts of the ERP benchmark questions, computed on the evaluated Odoo instance."""

import xmlrpc.client


class NotApplicable(Exception):
    pass


def amount_variants(value):
    integer, cents = f'{value:.2f}'.split('.')
    grouped = f'{int(integer):,}'
    variants = {f'{integer},{cents}', f'{integer}.{cents}', f'{grouped}.{cents}', f'{grouped.replace(",", ".")},{cents}'}
    if cents == '00':
        variants |= {integer, grouped, grouped.replace(',', '.')}
    return sorted(variants)


def _count(execute, spec):
    total = execute(spec['model'], 'search_count', [spec['domain']])
    if not total:
        raise NotApplicable('no matching record')
    return [[str(total)]]


def _sum(execute, spec):
    field = spec['field']
    groups = execute(spec['model'], 'read_group', [spec['domain'], [f'{field}:sum'], [spec['currency_field']]], {'lazy': False})
    if len(groups) != 1:
        raise NotApplicable('no matching record or several currencies')
    return [amount_variants(groups[0][field])]


def _top(execute, spec):
    field, groupby = spec.get('field'), spec['groupby']
    groups = execute(spec['model'], 'read_group', [spec['domain'], [f'{field}:sum'] if field else [], [groupby]], {'lazy': False})
    measure = field or '__count'
    ranked = sorted((group for group in groups if group[groupby]), key=lambda group: group[measure], reverse=True)
    if not ranked or (len(ranked) > 1 and ranked[0][measure] == ranked[1][measure]):
        raise NotApplicable('no single leader')
    return [[ranked[0][groupby][1]]]


KINDS = {'count': _count, 'sum': _sum, 'top': _top}


def compute_expected(execute, question):
    for module in question.get('requires', []):
        if not execute('ir.module.module', 'search_count', [[['name', '=', module], ['state', '=', 'installed']]]):
            raise NotApplicable(f'module {module} is not installed')
    spec = question['expectation']
    try:
        return KINDS[spec['kind']](execute, spec)
    except xmlrpc.client.Fault as fault:
        raise NotApplicable(f'Odoo refused the query: {fault.faultString.strip().splitlines()[-1]}') from fault
