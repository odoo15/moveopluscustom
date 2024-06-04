# -*- coding: utf-8 -*-
from functools import reduce
import operator

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _get_company_currency(self):
        for partner in self:
            company = partner.company_id or self.env.company
            partner.currency_id = company.sudo().currency_id

    # RELATION Fields [Many2many, One2many, Many2one]:
    line_ids = fields.One2many(
        comodel_name="mv.discount.partner",
        inverse_name="partner_id",
        copy=False,
        help="""
            Child Model: mv.discount.partner
            This field is used to store the discount policy of the Partner/Customer.
        """,
    )
    compute_discount_line_ids = fields.One2many(
        comodel_name="mv.compute.discount.line",
        inverse_name="partner_id",
        domain=[("parent_id", "!=", False)],
        copy=False,
        help="""
                Link Model: mv.compute.discount.line
                This field is used to store the computed discount of the Partner/Customer.
            """,
    )
    warranty_discount_policy_ids = fields.Many2many(
        comodel_name="mv.warranty.discount.policy",
        string="Chính sách chiết khấu kích hoạt",
        compute="_compute_discount_ids",
        store=True,
        readonly=False,
    )
    discount_id = fields.Many2one(
        comodel_name="mv.discount",
        string="Chiết khấu",
        compute="_compute_discount_ids",
        store=True,
        readonly=False,
    )
    sale_mv_ids = fields.Many2many("sale.order", copy=False, readonly=True)
    currency_id = fields.Many2one("res.currency", compute="_get_company_currency")
    # =================================
    is_agency = fields.Boolean("Đại lý", copy=False, tracking=True)
    is_white_agency = fields.Boolean("Đại lý vùng trắng", copy=False, tracking=True)
    bank_guarantee = fields.Boolean("Bảo lãnh ngân hàng", copy=False, tracking=True)
    discount_bank_guarantee = fields.Float(copy=False, tracking=True)

    # TOTAL Fields:
    amount = fields.Integer("Tiền chiết khấu", copy=False)
    amount_currency = fields.Monetary(
        string="Tiền chiết khấu hiện có",
        copy=False,
        readonly=True,
        currency_field="currency_id",
    )
    total_so_bonus_order = fields.Monetary(
        compute="_compute_sale_order_ids", store=True
    )

    # =================================
    # COMPUTE / ONCHANGE Methods
    # =================================

    @api.depends("line_ids")
    def _compute_discount_ids(self):
        for record in self:
            # Compute discount_id
            discount_line_ids = [line for line in record.line_ids if line.parent_id]
            record.discount_id = (
                discount_line_ids[0].parent_id.id if discount_line_ids else False
            )

            # Compute warranty_discount_policy_ids
            warranty_line_ids = [
                [(6, 0, line.warranty_discount_policy_ids.ids)]
                for line in record.line_ids
                if len(line.warranty_discount_policy_ids) > 0
            ]
            record.warranty_discount_policy_ids = warranty_line_ids

    @api.depends("sale_order_ids")
    def _compute_sale_order_ids(self):
        for record in self.filtered(lambda partner: partner.is_agency):
            record.sale_mv_ids = None
            orders_discount = [
                order
                for order in record.sale_order_ids
                if order.bonus_order > 0 and order.state != "cancel"
            ]
            if orders_discount:
                record.sale_mv_ids = [(6, 0, [order.id for order in orders_discount])]

            record.total_so_bonus_order = reduce(
                operator.add, (order.bonus_order for order in orders_discount), 0
            )
            record.amount_currency = (
                sum(line.total_money for line in record.compute_discount_line_ids)
                - record.total_so_bonus_order
            )

    @api.onchange("discount_id")
    def _onchange_discount_id(self):
        if self.discount_id:
            for line in self.line_ids.filtered(lambda r: r.partner_id.id == self.id):
                line.write({"needs_update": True})

    @api.onchange("warranty_discount_policy_ids")
    def _onchange_warranty_discount_policy_id(self):
        if self.warranty_discount_policy_ids:
            for line in self.line_ids.filtered(lambda r: r.partner_id.id == self.id):
                line.write({"needs_update": True})

    @api.onchange("is_white_agency")
    def _onchange_is_white_agency(self):
        if self.is_white_agency:
            self.is_agency = True

    @api.onchange("bank_guarantee")
    def _onchange_bank_guarantee(self):
        self.discount_bank_guarantee = 0

    # =================================
    # ACTION Methods
    # =================================

    def action_update_discount_amount(self):
        self.ensure_one()
        if self.is_agency:
            if self.sale_order_ids:
                orders_discount = [
                    order
                    for order in self.sale_order_ids
                    if order.bonus_order > 0 and order.state in ["sent", "sale"]
                ]
                if orders_discount:
                    self.sale_mv_ids = [(6, 0, [order.id for order in orders_discount])]
                    self.total_so_bonus_order = sum(
                        order.bonus_order for order in orders_discount
                    )

            if self.compute_discount_line_ids:
                self.amount_currency = (
                    sum(line.total_money for line in self.compute_discount_line_ids)
                    - self.total_so_bonus_order
                )
