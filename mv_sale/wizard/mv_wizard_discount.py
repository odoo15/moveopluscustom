# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

DISCOUNT_PERCENTAGE_DIVISOR = 100

MOVEOPLUS_TITLES = {
    "add_a_shipping_method": "Thêm phương thức giao hàng",
}

MOVEOPLUS_MESSAGES = {
    "discount_amount_apply_exceeded": "Tiền chiết khấu áp dụng không được lớn hơn số tiền chiết khấu tối đa.",
    "discount_amount_invalid": "Tiền chiết khấu áp dụng đang lớn số tiền chiết khấu hiện có, vui lòng nhập lại!",
}


class MvWizardDeliveryCarrierAndDiscountPolicyApply(models.TransientModel):
    _name = "mv.wizard.discount"
    _description = _("Wizard: Delivery Carrier & Discount Policy Apply")

    def _get_default_weight_uom(self):
        return self.env[
            "product.template"
        ]._get_weight_uom_name_from_ir_config_parameter()

    # === Sale Order Fields ===#
    sale_order_id = fields.Many2one("sale.order", required=True)
    company_id = fields.Many2one("res.company", related="sale_order_id.company_id")
    currency_id = fields.Many2one("res.currency", related="sale_order_id.currency_id")
    partner_id = fields.Many2one(
        "res.partner", related="sale_order_id.partner_id", required=True
    )
    is_update = fields.Boolean(compute="_compute_sale_order_id")

    # === Delivery Carrier Fields ===#
    delivery_set = fields.Boolean(compute="_compute_sale_order_id")
    carrier_id = fields.Many2one("delivery.carrier", required=True)
    delivery_type = fields.Selection(related="carrier_id.delivery_type")
    delivery_price = fields.Float()
    display_price = fields.Float(string="Cost", readonly=True)
    available_carrier_ids = fields.Many2many(
        "delivery.carrier",
        compute="_compute_available_carrier",
        string="Available Carriers",
    )
    invoicing_message = fields.Text(compute="_compute_invoicing_message")
    delivery_message = fields.Text(readonly=True)
    total_weight = fields.Float(
        string="Total Order Weight",
        related="sale_order_id.shipping_weight",
        readonly=False,
    )
    weight_uom_name = fields.Char(readonly=True, default=_get_default_weight_uom)

    # === Discount Policy Fields ===#
    discount_agency_set = fields.Boolean(compute="_compute_sale_order_id")
    discount_amount_invalid = fields.Boolean(readonly=True)
    discount_amount_invalid_message = fields.Text(readonly=True)
    discount_amount_apply = fields.Float()
    discount_amount_maximum = fields.Float(related="sale_order_id.bonus_max")
    discount_amount_remaining = fields.Float(compute="_compute_sale_order_id")
    discount_amount_applied = fields.Float(compute="_compute_sale_order_id")

    # ==================================
    # CONSTRAINS / VALIDATION Methods
    # ==================================

    @api.constrains(
        "discount_amount_apply", "discount_amount_applied", "discount_amount_maximum"
    )
    def _check_discount_amount_apply_exceeded(self):
        for wizard in self:
            total_applied = (
                wizard.discount_amount_applied + wizard.discount_amount_apply
            )
            if (
                wizard.discount_amount_applied == 0
                and wizard.discount_amount_apply > wizard.discount_amount_maximum
            ) or (
                wizard.discount_amount_applied != 0
                and total_applied > wizard.discount_amount_maximum
            ):
                raise ValidationError(
                    MOVEOPLUS_MESSAGES["discount_amount_apply_exceeded"]
                )

    # ==================================
    # COMPUTE / ONCHANGE Methods
    # ==================================

    @api.onchange("discount_amount_invalid")
    def onchange_discount_amount_invalid_message(self):
        if self.discount_amount_invalid:
            self.discount_amount_invalid_message = MOVEOPLUS_MESSAGES[
                "discount_amount_invalid"
            ]

    @api.depends("sale_order_id", "sale_order_id.order_line")
    def _compute_sale_order_id(self):
        for wizard in self:
            order = wizard.sale_order_id
            wizard.is_update = order.recompute_discount_agency
            wizard.delivery_set = any(line.is_delivery for line in order.order_line)
            wizard.discount_agency_set = order.order_line._filter_discount_agency_lines(
                order
            )
            total_remaining = wizard.partner_id.amount_currency - order.bonus_order
            wizard.discount_amount_remaining = (
                total_remaining if total_remaining > 0 else 0.0
            )
            wizard.discount_amount_applied = (
                order.bonus_order if not wizard.discount_amount_invalid else 0.0
            )

    @api.depends("carrier_id")
    def _compute_invoicing_message(self):
        self.ensure_one()
        self.invoicing_message = ""

    @api.depends("partner_id")
    def _compute_available_carrier(self):
        for rec in self:
            carriers = self.env["delivery.carrier"].search(
                self.env["delivery.carrier"]._check_company_domain(
                    rec.sale_order_id.company_id
                )
            )
            rec.available_carrier_ids = (
                carriers.available_carriers(rec.sale_order_id.partner_shipping_id)
                if rec.partner_id
                else carriers
            )

    @api.onchange("carrier_id", "total_weight")
    def _onchange_carrier_id(self):
        self.delivery_message = False
        if self.delivery_type in ("fixed", "base_on_rule"):
            vals = self._get_shipment_rate()
            if vals.get("error_message"):
                return {"error": vals["error_message"]}

    @api.onchange("sale_order_id")
    def _onchange_order_id(self):
        # fixed and base_on_rule delivery price will compute on each carrier change so no need to recompute here
        if (
            self.carrier_id
            and self.sale_order_id.delivery_set
            and self.delivery_type not in ("fixed", "base_on_rule")
        ):
            vals = self._get_shipment_rate()
            if vals.get("error_message"):
                warning = {
                    "title": _("%(carrier)s Error", carrier=self.carrier_id.name),
                    "message": vals["error_message"],
                    "type": "notification",
                }
                return {"warning": warning}

    # ==================================
    # BUSINESS Methods
    # ==================================

    def _get_shipment_rate(self):
        vals = self.carrier_id.with_context(
            order_weight=self.total_weight
        ).rate_shipment(self.sale_order_id)
        if vals.get("success"):
            self.delivery_message = vals.get("warning_message", False)
            self.delivery_price = vals["price"]
            self.display_price = vals["carrier_price"]
            return {}
        return {"error_message": vals["error_message"]}

    def update_price(self):
        vals = self._get_shipment_rate()
        if vals.get("error_message"):
            raise UserError(vals.get("error_message"))
        return {
            "name": MOVEOPLUS_TITLES["add_a_shipping_method"],
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "choose.delivery.carrier",
            "res_id": self.id,
            "target": "new",
        }

    def _prepare_mv_discount_product_ckt_values(self):
        self.ensure_one()
        return {
            "name": "Chiết khấu sản lượng (Tháng, Quý, Năm)",
            "default_code": "CKT",
            "type": "service",
            "invoice_policy": "order",
            "list_price": 0.0,
            "company_id": self.company_id.id,
            "taxes_id": None,
        }

    def _prepare_mv_discount_line_values(self, product, amount, description=None):
        self.ensure_one()

        vals = {
            "order_id": self.sale_order_id.id,
            "product_id": product.id,
            "product_uom_qty": 1,
            "code_product": "CKT",
            "price_unit": -amount,
            "hidden_show_qty": True,
            "sequence": 999,
        }
        if description:
            # If not given, name will fall back on the standard SOL logic (cf. _compute_name)
            vals["name"] = description

        return vals

    def _get_mv_discount_product(self):
        """Return product.product used for moveoplus discount line"""
        self.ensure_one()
        discount_product = self.env["product.product"].search(
            [("default_code", "=", "CKT")], limit=1
        )
        if not discount_product:
            self.company_id.sale_discount_product_id = self.env[
                "product.product"
            ].create(self._prepare_mv_discount_product_ckt_values())
            discount_product = self.company_id.sale_discount_product_id
        return discount_product

    def action_apply(self):
        wizard = self.with_company(self.company_id)
        order = wizard.sale_order_id

        if not wizard.delivery_set:
            order.set_delivery_line(wizard.carrier_id, wizard.delivery_price)
            order.write(
                {
                    "recompute_delivery_price": False,
                    "delivery_message": wizard.delivery_message,
                }
            )

        if not wizard.discount_agency_set:
            """Create SOline(s) discount according to wizard configuration"""
            # discount_product = self._get_mv_discount_product()
            # vals_list = [
            #     {
            #         **self._prepare_mv_discount_line_values(
            #             product=discount_product, amount=self.discount_amount_apply
            #         ),
            #     }
            # ]
            # order.order_line.create(vals_list)
            order.compute_discount_for_partner(wizard.discount_amount_apply)
            order._handle_bank_guarantee_discount()

        order._update_programs_and_rewards()
        order._auto_apply_rewards()

        return True

    def action_update(self):
        wizard = self.with_company(self.company_id)
        order = wizard.sale_order_id

        # [>] For Product Discount with code 'CKT'
        if wizard.discount_agency_set:
            """Update SOline(s) discount according to wizard configuration"""

            total_order_discount_CKT = (
                (wizard.discount_amount_apply + wizard.discount_amount_applied)
                if wizard.discount_amount_remaining > 0
                else wizard.discount_amount_apply
            )
            order.order_line.filtered(
                lambda line: line.product_id.default_code == "CKT"
            ).write(
                {
                    "price_unit": (
                        -total_order_discount_CKT
                        if total_order_discount_CKT > 0
                        else 0.0
                    )
                }
            )
            order._compute_partner_bonus()
            order._compute_bonus_order_line()

        # [>] For Product Discount with code 'CKBL'
        if order.bank_guarantee:
            total_order_discount_CKBL = (
                order.total_price_after_discount
                * order.partner_id.discount_bank_guarantee
                / DISCOUNT_PERCENTAGE_DIVISOR
            )
            order.order_line.filtered(
                lambda line: line.product_id.default_code == "CKBL"
            ).write({"price_unit": -total_order_discount_CKBL})

        order._update_programs_and_rewards()
        order._auto_apply_rewards()

        return True

    def action_apply_and_confirm(self):
        self.action_update()
        return self.sale_order_id.with_context(apply_confirm=True).action_confirm()
