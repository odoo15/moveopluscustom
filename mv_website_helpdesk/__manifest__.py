# -*- coding: utf-8 -*-
{
    'name': 'MV Website Helpdesk',
    'version': '17.0.1.0',
    'category': 'Moveoplus/MV Website Helpdesk',
    'description': "Base on Website Helpdesk module to customize new features",
    'author': 'Phat Dang <phat.dangminh@moveoplus.com>',
    'depends': [
        # Odoo (Enterprice)
        'website_helpdesk',
        # Moveoplus
        'mv_helpdesk',
    ],
    'data': [
        # SECURITY
        'security/ir.model.access.csv',
        # DATA
        'data/helpdesk_data.xml',
        # VIEWS
        'views/helpdesk_templates.xml',
    ],
    'license': 'LGPL-3',
    'application': True,
}
