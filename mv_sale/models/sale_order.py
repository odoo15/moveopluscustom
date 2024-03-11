# -*- coding: utf-8 -*-

from odoo import models, api, fields


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    check_discount_10 = fields.Boolean(compute="_compute_check_discount_10", store=True, copy=False)
    total_price_no_service = fields.Float(compute="_compute_check_discount_10", help="Total price no include product service, no discount, no tax", store=True, copy=False)
    total_price_discount = fields.Float(compute="_compute_check_discount_10", help="Total price discount no include product service, no tax", store=True, copy=False)
    percentage = fields.Float(compute="_compute_check_discount_10", help="% discount of pricelist", store=True, copy=False)
    total_price_after_discount = fields.Float(compute="_compute_check_discount_10", help="Total price after discount no include product service, no tax", store=True, copy=False)
    total_price_discount_10 = fields.Float(compute="_compute_check_discount_10", help="Total price discount 1% when product_uom_qty >= 10", store=True, copy=False)
    total_price_after_discount_10 = fields.Float(compute="_compute_check_discount_10", help="Total price after discount 1% when product_uom_qty >= 10", store=True, copy=False)
    # tổng số tiền tối đa mà khách hàng có thể áp dụng chiết khấu từ tài khoản bonus của mình
    bonus_max = fields.Float(compute="_compute_check_discount_10", help="Total price after discount 1% when product_uom_qty >= 10", store=True, copy=False)
    # tổng số tiền mà khách hàng đã áp dụng giảm chiết khấu
    bonus_order = fields.Float(copy=False)
    discount_line_id = fields.Many2one("mv.compute.discount.line")

    # thuật toán kiếm cha là lốp xe
    def check_category_product(self, categ_id):
        if categ_id.id == 19:
            return True
        if categ_id.parent_id:
            return self.check_category_product(categ_id.parent_id)
        return False

    def check_show_warning(self):
        order_line = self.order_line.filtered(lambda x: x.product_id.detailed_type == 'product' and x.order_id.check_category_product(x.product_id.categ_id))
        if len(order_line) >= 1 and sum(order_line.mapped('product_uom_qty')) < 4:
            return True
        return False

    def compute_discount_for_partner(self, bonus):
        if bonus > self.bonus_max:
            return False
        else:
            if bonus > self.partner_id.amount:
                return bonus
            total_bonus = bonus + self.bonus_order
            print(self.bonus_order)
            if total_bonus > self.bonus_max:
                return total_bonus
            order_line_id = self.order_line.filtered(lambda x: x.product_id.default_code == 'CKSL')
            if len(order_line_id) == 0:
                product_tmpl_id = self.env['product.template'].search([('default_code', '=', 'CKSL')])
                if not product_tmpl_id:
                    product_tmpl_id = self.env['product.template'].create({
                        'name': 'Chiết khấu sản lượng',
                        'detailed_type': 'service',
                        'categ_id': 1,
                        'taxes_id': False,
                        'default_code': 'CKSL'
                    })
                order_line_id = self.env['sale.order.line'].create({
                    'product_id': product_tmpl_id.product_variant_ids[0].id,
                    'order_id': self.id,
                    'product_uom_qty': 1,
                    'price_unit': 0,
                    'hidden_show_qty': True,
                })
            order_line_id.write({
                'price_unit': - total_bonus,
            })
            self.write({
                'bonus_order': total_bonus
            })
            self.partner_id.write({
                'amount': self.partner_id.amount - bonus
            })

    @api.depends('order_line', 'order_line.product_uom_qty', 'order_line.product_id')
    def _compute_check_discount_10(self):
        for record in self:
            record.check_discount_10 = False
            record.total_price_no_service = 0
            record.total_price_discount = 0
            record.percentage = 0
            record.total_price_after_discount = 0
            record.total_price_discount_10 = 0
            record.total_price_after_discount_10 = 0
            record.bonus_max = 0
            # kiểm tra xem thỏa điều kiện để mua đủ trên 10 lốp xe condinental
            if record.partner_id.is_agency and len(record.order_line) > 0:
                order_line = self.order_line.filtered(lambda x: x.product_id.detailed_type == 'product' and x.order_id.check_category_product(x.product_id.categ_id))
                if len(order_line) >= 1 and sum(order_line.mapped('product_uom_qty')) >= 10:
                    record.check_discount_10 = True
            # tính tổng tiền giá sản phầm không bao gồm hàng dịch vụ, tính giá gốc ban đầu, không bao gồm thuế phí
            if len(record.order_line) > 0:
                total_price_no_service = 0
                total_price_discount = 0
                percentage = 0
                for line in record.order_line.filtered(lambda x: x.product_id.detailed_type == 'product'):
                    total_price_no_service = total_price_no_service + line.price_unit * line.product_uom_qty
                    total_price_discount = total_price_discount + line.price_unit * line.product_uom_qty * line.discount / 100
                    percentage = line.discount
                record.total_price_no_service = total_price_no_service
                record.total_price_discount = total_price_discount
                record.percentage = percentage
                record.total_price_after_discount = record.total_price_no_service - record.total_price_discount
                record.total_price_discount_10 = record.total_price_after_discount / 100
                record.total_price_after_discount_10 = record.total_price_after_discount  - record.total_price_discount_10
                record.bonus_max = (record.total_price_no_service - record.total_price_discount - record.total_price_discount_10) / 2

    def action_cancel(self):
        if self.bonus_order > 0:
            self.partner_id.write({
                'amount': self.partner_id.amount + self.bonus_order
            })
            self.write({
                'bonus_order': 0
            })
        return super().action_cancel()