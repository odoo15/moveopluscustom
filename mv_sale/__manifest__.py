# -*- coding: utf-8 -*-
{
    "name": "MV Sale",
    "version": "17.0.1.0",
    "category": "Moveoplus/MV Sale",
    "description": "Base on Sale modules and Related modules to customize new features",
    "author": "Phat Dang <phat.dangminh@moveoplus.com>",
    "depends": [
        # Odoo
        "account",
        "sale",
        "sale_loyalty",
        "sale_management",
        "sale_stock",
        "website_sale",
        "website_sale_loyalty",
        # Biz
        "biz_viettel_sinvoice_v2",
        # Moveoplus
        "mv_base",
    ],
    "data": [
        # SECURITY
        "security/res_groups.xml",
        "security/ir_rules.xml",
        "security/ir.model.access.csv",
        # DATA
        "data/ir_cron_data.xml",
        # VIEWS
        "views/mv_discount_views.xml",
        "views/mv_discount_partner_views.xml",
        "views/mv_promote_discount_line_views.xml",
        "views/mv_warranty_discount_policy_views.xml",
        "views/mv_white_place_discount_line_views.xml",
        "views/product_attribute_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "views/mv_compute_discount_views.xml",
        "views/mv_compute_discount_line_views.xml",
        "views/mv_compute_warranty_discount_policy_views.xml",
        "views/templates.xml",
        # REPORT
        "report/discount_report_views.xml",
        # WIZARD
        "wizard/mv_wizard_discount_views.xml",
        "wizard/mv_report_discount_views.xml",
        "wizard/mv_wizard_promote_discount_line_views.xml",
        "wizard/mv_wizard_update_partner_discount_views.xml",
        # MENU
        "views/menus.xml",
    ],
    "bootstrap": True,
    "assets": {
        "web.assets_backend": [
            "mv_sale/static/src/scss/mv_sale_style.scss",
        ],
    },
    "license": "LGPL-3",
    "application": True,
}
