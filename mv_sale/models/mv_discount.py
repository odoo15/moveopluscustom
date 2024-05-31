# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MvDiscountPolicy(models.Model):
    _name = "mv.discount"
    _description = _("MOVEO PLUS Discount Policy")

    active = fields.Boolean("Active", default=True)
    name = fields.Char("Chính sách chiết khấu")
    line_ids = fields.One2many("mv.discount.line", "parent_id")
    level_promote_apply = fields.Integer("Level")
    line_promote_ids = fields.One2many("mv.promote.discount.line", "parent_id")
    line_white_place_ids = fields.One2many("mv.white.place.discount.line", "parent_id")
    partner_ids = fields.One2many(
        "mv.discount.partner",
        "parent_id",
        domain=[("partner_id.is_agency", "=", True)],
    )

    @api.constrains("line_ids", "level_promote_apply")
    def validate_out_of_current_level(self):
        for rec in self.filtered("line_ids"):
            max_level = max(rec.line_ids.mapped("level"))
            if rec.level_promote_apply > max_level:
                raise ValidationError(
                    _("Bậc cao nhất hiện tại là %s, vui lòng nhập lại!") % max_level
                )
