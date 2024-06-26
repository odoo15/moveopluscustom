# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

TARGET_CATEGORY_ID = 19
DISCOUNT_PERCENTAGE_DIVISOR = 100
DISCOUNT_QUANTITY_THRESHOLD = 10
QUANTITY_THRESHOLD = 4

GROUP_SALES_MANAGER = "sales_team.group_sale_manager"


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # === Permission/Flags Fields ===#
    is_sales_manager = fields.Boolean(compute="_compute_permissions")
    discount_agency_set = fields.Boolean(
        compute="_compute_permissions",
        help="""Ghi nhận: Khi có bổ sung "Chiết khấu sản lượng (Tháng/Quý/Năm)" trên đơn bán.""",
    )
    compute_discount_agency = fields.Boolean(compute="_compute_permissions")
    recompute_discount_agency = fields.Boolean(
        "Discount Agency Amount should be recomputed"
    )

    @api.depends(
        "state", "order_line", "order_line.product_id", "order_line.product_uom_qty"
    )
    @api.depends_context("uid", "compute_discount_agency", "recompute_discount_agency")
    def _compute_permissions(self):
        for order in self:
            order.is_sales_manager = self.env.user.has_group(GROUP_SALES_MANAGER)
            order.discount_agency_set = order.order_line._filter_discount_agency_lines(
                order
            )
            order.compute_discount_agency = (
                order.state
                in [
                    "draft",
                    "sent",
                ]
                and not order.discount_agency_set
                and order.partner_agency
            )
            order.recompute_discount_agency = (
                order.state
                in [
                    "draft",
                    "sent",
                ]
                and order.discount_agency_set
                and order.partner_agency
            )

    # === Model: [res.partner] Fields ===#
    partner_agency = fields.Boolean(related="partner_id.is_agency", store=True)
    partner_white_agency = fields.Boolean(
        related="partner_id.is_white_agency", store=True
    )
    partner_southern_agency = fields.Boolean(
        related="partner_id.is_southern_agency", store=True
    )
    bank_guarantee = fields.Boolean(related="partner_id.bank_guarantee", store=True)
    discount_bank_guarantee = fields.Float(compute="_compute_discount", store=True)
    after_discount_bank_guarantee = fields.Float(
        compute="_compute_discount", store=True
    )

    # === Model: [mv.compute.discount.line] Fields ===#
    discount_line_id = fields.Many2one("mv.compute.discount.line", readonly=True)

    check_discount_10 = fields.Boolean(compute="_compute_discount", store=True)
    # === Bonus, Discount Fields ===#
    percentage = fields.Float(compute="_compute_discount", store=True)
    bonus_max = fields.Float(
        compute="_compute_discount",
        store=True,
        help="Số tiền tối đa mà Đại lý có thể áp dụng để tính chiết khấu.",
    )
    bonus_order = fields.Float(
        compute="_compute_bonus",
        store=True,
        help="Số tiền chiết khấu đã và đang áp dụng trên đơn bán.",
    )
    bonus_remaining = fields.Float(
        compute="_compute_bonus",
        store=True,
        help="Số tiền còn lại mà Đại lý có thể áp dụng để tính chiết khấu.",
    )

    @api.depends(
        "partner_id",
        "order_line",
        "order_line.product_id",
        "order_line.product_uom_qty",
    )
    def _compute_bonus(self):
        for order in self:
            bonus_order = sum(
                line.price_unit
                for line in order.order_line._filter_discount_agency_lines(order)
            )
            order.bonus_order = abs(bonus_order)
            order.bonus_remaining = order.partner_id.amount_currency - abs(bonus_order)

    # === Amount, Total Fields ===#
    total_price_no_service = fields.Float(
        compute="_compute_discount",
        store=True,
        help="Total price without Product Service, No Discount, No Tax",
    )
    total_price_discount = fields.Float(
        compute="_compute_discount",
        store=True,
        help="Total price discount without Product Service, No Tax",
    )
    total_price_after_discount = fields.Float(
        compute="_compute_discount",
        store=True,
        help="Total price after discount without Product Service, No Tax",
    )
    total_price_discount_10 = fields.Float(
        compute="_compute_discount",
        help="Total price discount 1% when [product_uom_qty] >= 10",
        store=True,
    )
    total_price_after_discount_10 = fields.Float(
        compute="_compute_discount",
        store=True,
        help="Total price after discount 1% when [product_uom_qty] >= 10",
    )
    total_price_after_discount_month = fields.Float(
        compute="_compute_discount",
        store=True,
        help="Total price after discount for a month",
    )
    # === Other Fields ===#
    is_order_returns = fields.Boolean(
        default=False, help="Ghi nhận: Là đơn đổi/trả hàng."
    )  # TODO: Needs study cases for SO Returns
    date_invoice = fields.Datetime(readonly=True)
    quantity_change = fields.Float(readonly=True)

    def check_category_product(self, categ_id):
        """
        Check if the given product category or any of its parent categories have an ID of TARGET_CATEGORY_ID.

        Args:
            categ_id (models.Model): The product category to check.

        Returns:
            bool: True if the product category
            or any of its parent categories have an ID of TARGET_CATEGORY_ID, False otherwise.
        """
        try:
            if categ_id.id == TARGET_CATEGORY_ID:
                return True
            if categ_id.parent_id:
                return self.check_category_product(categ_id.parent_id)
        except AttributeError as e:
            _logger.error("Failed to check category product: %s", e)
            return False
        return False

    def check_show_warning(self):
        """
        Check if there is at least one product in the order line that belongs to the target category
        and if the sum of the quantities of these products is less than QUANTITY_THRESHOLD.

        Returns:
            bool: True if both conditions are met, False otherwise.
        """
        order_line = self.order_line.filtered(
            lambda line: line.product_id.product_tmpl_id.detailed_type == "product"
            and self.check_category_product(x.product_id.categ_id)
        )
        return (
            len(order_line) >= 1
            and sum(order_line.mapped("product_uom_qty")) < QUANTITY_THRESHOLD
        )

    def _compute_cart_info(self):
        # TODO: Move to 'mv_website_sale' module
        # Call the parent class's _compute_cart_info method
        super(SaleOrder, self)._compute_cart_info()

        # Iterate over each order in the recordset
        for order in self:
            # Calculate the total quantity of all service lines that are not reward lines
            # This is done by summing the "product_uom_qty" field of each line in the order's "website_order_line" field
            # that has a product with a "detailed_type" not equal to "product" and is not a reward line
            service_lines_qty = sum(
                line.product_uom_qty
                for line in order.website_order_line
                if line.product_id.product_tmpl_id.detailed_type != "product"
                and not line.is_reward_line
            )

            # Subtract the total quantity of service lines from the order's "cart_quantity"
            # The int() function is used to ensure that the result is an integer
            order.cart_quantity -= int(service_lines_qty)

    def _get_order_lines_to_report(self):
        Orders = super(SaleOrder, self)._get_order_lines_to_report()
        return Orders.sorted(
            key=lambda order: order.product_id.product_tmpl_id.detailed_type
        )

    # ==================================

    @api.depends("order_line", "order_line.product_uom_qty", "order_line.product_id")
    def _compute_discount(self):
        for order in self:
            # TODO: Improve the logic of this method - Deadline: 25/06/2024 - Developer: phat.dangminh@moveoplus.com
            # RESET all discount values
            order.reset_discount_values()

            # [!] Kiểm tra có phải Đại lý trực thuộc của MOVEO+ hay không?
            partner_agency = order.partner_id.is_agency
            if order.order_line:
                # [!] Kiểm tra xem thỏa điều kiện để mua đủ trên 10 lốp xe continental
                order.check_discount_10 = (
                    order.check_discount_applicable() if partner_agency else False
                )
                # [!] Tính tổng tiền giá sản phẩm không bao gồm hàng Dịch Vụ,
                #      tính giá gốc ban đầu, không bao gồm Thuế
                order.calculate_discount_values()

            # [!] Nếu đơn hàng không còn lốp xe nữa thì xóa:
            # - "Chiết Khấu Tháng" (CKT)
            # - "Chiết Khấu Bảo Lãnh" (CKBL)
            # - "Chiết khấu Vùng Trắng" (CKSLVT) (Nếu có tồn tại)
            # - "Chiết khấu Miền Nam" (CKSLMN) (Nếu có tồn tại)
            order.handle_discount_lines()

    def reset_discount_values(self):
        self.percentage = 0
        self.check_discount_10 = False
        self.total_price_no_service = 0
        self.total_price_discount = 0
        self.total_price_after_discount = 0
        self.total_price_discount_10 = 0
        self.total_price_after_discount_10 = 0
        self.total_price_after_discount_month = 0
        self.bonus_max = 0

    def check_discount_applicable(self):
        order_lines = self.order_line.filtered(
            lambda sol: self.check_category_product(sol.product_id.categ_id)
            and sol.product_id.product_tmpl_id.detailed_type == "product"
        )

        return (
            len(order_lines) >= 1
            and sum(order_lines.mapped("product_uom_qty"))
            >= DISCOUNT_QUANTITY_THRESHOLD
        )

    def calculate_discount_values(self):
        percentage = 0
        total_price_no_service = 0
        total_price_discount = 0

        for line in self.order_line.filtered(
            lambda sol: sol.product_id.product_tmpl_id.detailed_type == "product"
        ):
            total_price_no_service += line.price_unit * line.product_uom_qty
            total_price_discount += (
                line.price_unit
                * line.product_uom_qty
                * line.discount
                / DISCOUNT_PERCENTAGE_DIVISOR
            )
            percentage = line.discount

        self.percentage = percentage
        self.total_price_no_service = total_price_no_service
        self.total_price_discount = total_price_discount
        self.total_price_after_discount = (
            self.total_price_no_service - self.total_price_discount
        )

        self.total_price_discount_10 = (
            self.total_price_after_discount / DISCOUNT_PERCENTAGE_DIVISOR
        )
        self.total_price_after_discount_10 = (
            self.after_discount_bank_guarantee - self.total_price_discount_10
        )
        self.total_price_after_discount_month = (
            self.total_price_after_discount_10 - self.bonus_order
        )

        self.bonus_max = (
            self.total_price_no_service
            - self.total_price_discount
            - self.total_price_discount_10
            - self.discount_bank_guarantee
        ) / 2

    def handle_discount_lines(self):
        """
        Removes discount lines from the order if there are no more products in the order.
        Specifically, it checks for the existence of order lines with provided product codes
        and removes them if there are no more products in the order.
        """
        discount_product_codes = {"CKT", "CKBL"}
        if self.partner_white_agency:
            discount_product_codes.add("CKSLVT")  # CKSLVT: Chiết khấu Đại lý vùng trắng

        if self.partner_southern_agency:
            discount_product_codes.add("CKSLMN")  # CKSLMN: Chiết khấu Đại lý miền Nam

        # [>] Separate order lines into discount lines and product lines
        discount_lines = self.order_line.filtered(
            lambda sol: sol.product_id.default_code in discount_product_codes
        )
        product_lines = self.order_line.filtered(
            lambda sol: sol.product_id.product_tmpl_id.detailed_type == "product"
        )

        # [>] Unlink discount lines if there are no product lines in the order
        if discount_lines and not product_lines:
            discount_lines.unlink()

    # ==================================
    # ORM / CURD Methods
    # ==================================

    def write(self, vals):
        context = self.env.context.copy()
        _logger.debug(f"Context: {context}")
        return super(SaleOrder, self.with_context(context)).write(vals)

    def unlink(self):
        return super(SaleOrder, self).unlink()

    # ==================================
    # BUSINESS Methods
    # ==================================

    def compute_discount_for_partner(self, bonus):
        default_code = "CKT"
        try:
            bonus_max = self.bonus_max
            if bonus > bonus_max:
                return False
            else:
                if not self.partner_id:
                    _logger.warning("No partner found for this order.")
                    return False
                if bonus > self.partner_id.amount:
                    return bonus
                total_bonus = bonus + self.bonus_order
                if total_bonus > bonus_max:
                    return total_bonus

                # Filter order lines for products
                product_order_lines = self.order_line.filtered(
                    lambda sol: sol.product_id.default_code == default_code
                )
                if not product_order_lines:
                    # Create new product template if it doesn't exist
                    product_discount = self.env["product.template"].search(
                        [("default_code", "=", default_code)]
                    )
                    if not product_discount:
                        product_discount = (
                            self.env["product.template"]
                            .sudo()
                            .create(
                                {
                                    "name": "Chiết khấu tháng",
                                    "detailed_type": "service",
                                    "categ_id": 1,
                                    "taxes_id": False,
                                    "default_code": default_code,
                                }
                            )
                        )

                    # Check for existing discount line
                    discount_order_line = self.order_line.filtered(
                        lambda sol: sol.product_id.default_code == default_code
                    )
                    if not discount_order_line:
                        self.env["sale.order.line"].create(
                            {
                                "order_id": self.id,
                                "product_id": product_discount.product_variant_ids[
                                    0
                                ].id,
                                "code_product": default_code,
                                "product_uom_qty": 1,
                                "price_unit": -total_bonus,
                                "hidden_show_qty": True,
                            }
                        )
                        _logger.info("Created discount line for partner.")
                else:
                    # Update price unit of the order line
                    self.order_line.filtered(
                        lambda sol: sol.product_id.default_code == default_code
                    ).write(
                        {
                            "price_unit": -total_bonus,
                        }
                    )

            # [>] Update the Sale Order's Bonus Order
            self._compute_bonus()
            return True
        except Exception as e:
            _logger.error("Failed to compute discount for partner: %s", e)
            return False

    def action_compute_discount(self):
        if self._is_order_returns() or not self.order_line:
            return

        if self.locked:
            raise UserError("Không thể nhập chiết khấu sản lượng cho đơn hàng đã khóa.")

        quantity_change = self._calculate_quantity_change()
        discount_lines, delivery_lines = self._filter_order_lines()
        self._handle_quantity_change(quantity_change, discount_lines, delivery_lines)

        return self._handle_discount_applying()

    def action_recompute_discount(self):
        if self._is_order_returns() or not self.order_line:
            return

        if self.locked:
            raise UserError("Không thể nhập chiết khấu sản lượng cho đơn hàng đã khóa.")

        quantity_change = self._calculate_quantity_change()
        discount_lines, delivery_lines = self._filter_order_lines()

        self._handle_quantity_change(quantity_change, discount_lines, delivery_lines)

        return self._handle_discount_applying()

    def create_discount_bank_guarantee(self):
        order = self
        default_code = "CKBL"

        # [!] Kiểm tra tồn tại Sản Phẩm dịch vụ cho Chiết Khấu Bảo Lãnh
        product_discount_CKBL = self.env["product.product"].search(
            [("default_code", "=", default_code)], limit=1
        )
        if not product_discount_CKBL:
            self.env["product.product"].sudo().create(
                {
                    "name": "Chiết khấu bảo lãnh",
                    "default_code": "CKBL",
                    "type": "service",
                    "invoice_policy": "order",
                    "list_price": 0.0,
                    "company_id": self.company_id.id,
                    "taxes_id": None,
                }
            )

        # [!] Kiểm tra đã có dòng Chiết Khấu Bảo Lãnh hay chưa?
        discount_order_line = order.order_line.filtered(
            lambda sol: sol.product_id.default_code == default_code
        )
        if discount_order_line:
            # [>] Cập nhật giá sản phẩm
            discount_order_line.write(
                {
                    "price_unit": -order.total_price_after_discount
                    * order.partner_id.discount_bank_guarantee
                    / DISCOUNT_PERCENTAGE_DIVISOR,
                }
            )
        else:
            # [>] Tạo dòng Chiết Khấu Bảo Lãnh
            order.write(
                {
                    "order_line": [
                        (
                            0,
                            0,
                            {
                                "order_id": order.id,
                                "product_id": product_discount_CKBL.id,
                                "product_uom_qty": 1,
                                "code_product": default_code,
                                "price_unit": -order.total_price_after_discount
                                * order.partner_id.discount_bank_guarantee
                                / DISCOUNT_PERCENTAGE_DIVISOR,
                                "hidden_show_qty": True,
                            },
                        )
                    ]
                }
            )
            _logger.info("Created discount line for bank guarantee.")

    def _handle_bank_guarantee_discount(self):
        if self.bank_guarantee:
            self.discount_bank_guarantee = (
                self.total_price_after_discount
                * self.partner_id.discount_bank_guarantee
                / DISCOUNT_PERCENTAGE_DIVISOR
            )
            if self.discount_bank_guarantee > 0:
                self.with_context(bank_guarantee=True).create_discount_bank_guarantee()

    def _calculate_quantity_change(self):
        return sum(
            line.product_uom_qty
            for line in self.order_line
            if self.check_category_product(line.product_id.categ_id)
            and line.product_id.product_tmpl_id.detailed_type == "product"
        )

    def _handle_quantity_change(self, quantity_change, discount_lines, delivery_lines):
        if (
            self.quantity_change != quantity_change
            and self.quantity_change != quantity_change
        ):
            if delivery_lines:
                delivery_lines.unlink()
            if discount_lines:
                discount_lines.unlink()

            self.write({"quantity_change": quantity_change})

    def _filter_order_lines(self):
        order_lines_discount = self.order_line._filter_discount_agency_lines(self)
        order_lines_delivery = self.order_line.filtered("is_delivery")
        return order_lines_discount, order_lines_delivery

    def _handle_discount_applying(self):
        context = dict(self.env.context or {})
        if not context.get("action_confirm", False) and context.get(
            "compute_discount_agency"
        ):
            view_id = self.env.ref("mv_sale.mv_wiard_discount_view_form").id
            order_lines_delivery = self.order_line.filtered(lambda sol: sol.is_delivery)
            carrier = (
                (
                    self.with_company(
                        self.company_id
                    ).partner_shipping_id.property_delivery_carrier_id
                    or self.with_company(
                        self.company_id
                    ).partner_shipping_id.commercial_partner_id.property_delivery_carrier_id
                )
                if not order_lines_delivery
                else self.carrier_id
            )

            return {
                "name": "Chiết khấu",
                "type": "ir.actions.act_window",
                "res_model": "mv.wizard.discount",
                "view_id": view_id,
                "views": [(view_id, "form")],
                "context": {
                    "default_sale_order_id": self.id,
                    "partner_id": self.partner_id.id,
                    "default_partner_id": self.partner_id.id,
                    "default_discount_amount_apply": self.bonus_remaining,
                    "default_carrier_id": carrier.id,
                    "default_total_weight": self._get_estimated_weight(),
                },
                "target": "new",
            }
        elif not context.get("action_confirm", False) and context.get(
            "recompute_discount_agency"
        ):
            view_id = self.env.ref("mv_sale.mv_wiard_discount_view_form").id
            order_lines_delivery = self.order_line.filtered(lambda sol: sol.is_delivery)
            carrier = (
                (
                    self.with_company(
                        self.company_id
                    ).partner_shipping_id.property_delivery_carrier_id
                    or self.with_company(
                        self.company_id
                    ).partner_shipping_id.commercial_partner_id.property_delivery_carrier_id
                )
                if not order_lines_delivery
                else self.carrier_id
            )

            return {
                "name": "Cập nhật chiết khấu",
                "type": "ir.actions.act_window",
                "res_model": "mv.wizard.discount",
                "view_id": view_id,
                "views": [(view_id, "form")],
                "context": {
                    "default_sale_order_id": self.id,
                    "partner_id": self.partner_id.id,
                    "default_partner_id": self.partner_id.id,
                    "default_discount_amount_apply": self.bonus_remaining,
                    "default_carrier_id": carrier.id,
                    "default_total_weight": self._get_estimated_weight(),
                },
                "target": "new",
            }

    def _reset_discount_agency(self):
        self.ensure_one()

        if self.bonus_order > 0:
            if self.partner_id:
                _logger.info("Adding bonus order amount back to partner's amount.")
                self.partner_id.write(
                    {"amount": self.partner_id.amount + self.bonus_order}
                )
            else:
                _logger.warning("No partner found for this order.")
                pass

            self.write({"bonus_order": 0, "quantity_change": 0})

        self.order_line.filtered(
            lambda sol: sol.product_id.default_code == "CKT"
        ).unlink()

    def action_clear_discount_lines(self):
        # Filter the order lines based on the conditions
        discount_lines = self.order_line.filtered(
            lambda line: line.product_id.default_code
            and line.product_id.default_code.startswith("CK")
            or line.is_delivery
        )

        # Unlink the discount lines
        if discount_lines:
            discount_lines.unlink()

        return True

    def action_draft(self):
        self._reset_discount_agency()
        return super(SaleOrder, self).action_draft()

    def action_cancel(self):
        self._reset_discount_agency()
        return super(SaleOrder, self).action_cancel()

    def action_confirm(self):
        if not all(
            order._can_not_confirmation_without_required_lines()
            for order in self.filtered(lambda order: order.partner_id.is_agency)
        ):
            error_message = (
                "Các đơn hàng sau không có phương thức vận chuyển hoặc dòng chiết khấu sản lượng để xác nhận: %s"
                % ", ".join(self.mapped("display_name")),
            )
            raise UserError(error_message)

        self._check_delivery_lines()
        self._check_order_not_free_qty_today()
        self._handle_agency_discount()

        return super(SaleOrder, self).action_confirm()

    # === MOVEO+ FULL OVERRIDE '_get_program_domain' ===#

    def _get_program_domain(self):
        """
        Returns the base domain that all programs have to comply to.
        """
        self.ensure_one()
        today = fields.Date.context_today(self)
        program_domain = [
            ("active", "=", True),
            ("sale_ok", "=", True),
            ("company_id", "in", (self.company_id.id, False)),
            "|",
            ("pricelist_ids", "=", False),
            ("pricelist_ids", "in", [self.pricelist_id.id]),
            "|",
            ("date_from", "=", False),
            ("date_from", "<=", today),
            "|",
            ("date_to", "=", False),
            ("date_to", ">=", today),
        ]

        # === ĐẠI LÝ CHÍNH THỨC ===#
        if (
            self.partner_agency
            and not self.partner_white_agency
            and not self.partner_southern_agency
        ):
            program_domain += [("partner_agency_ok", "=", self.partner_agency)]
        # === ĐẠI LÝ VÙNG TRẮNG ===#
        elif (
            self.partner_agency
            and self.partner_white_agency
            and not self.partner_southern_agency
        ):
            program_domain += [
                ("partner_white_agency_ok", "=", self.partner_white_agency)
            ]
        # === ĐẠI LÝ MIỀN NAM ===#
        elif (
            self.partner_agency
            and self.partner_southern_agency
            and not self.partner_white_agency
        ):
            program_domain += [
                ("partner_southern_agency_ok", "=", self.partner_southern_agency)
            ]

        return program_domain

    def _update_programs_and_rewards(self):
        """
        Update the programs and rewards of the order.
        """
        if self.env.context.get("compute_discount_agency") or self.env.context.get(
            "recompute_discount_agency"
        ):
            return super()._update_programs_and_rewards()

    # ==================================
    # CONSTRAINS / VALIDATION Methods
    # ==================================

    def _can_not_confirmation_without_required_lines(self):
        self.ensure_one()
        discount_agency_lines = self.order_line._filter_discount_agency_lines(self)
        return self.delivery_set and discount_agency_lines

    def _check_delivery_lines(self):
        delivery_lines = self.order_line.filtered(lambda sol: sol.is_delivery)
        if not delivery_lines:
            raise UserError("Không tìm thấy dòng giao hàng nào trong đơn hàng.")

    def _check_order_not_free_qty_today(self):
        if self.state not in ["draft", "sent"]:
            return

        # Use list comprehension instead of filtered method
        product_order_lines = [
            line
            for line in self.order_line
            if line.product_id.product_tmpl_id.detailed_type == "product"
        ]

        error_products = []
        if product_order_lines:
            for so_line in product_order_lines:
                if so_line.product_uom_qty > so_line.free_qty_today:
                    error_products.append(
                        f"\n- {so_line.product_template_id.name}. [ Số lượng có thể đặt: {int(so_line.free_qty_today)} (Cái) ]"
                    )

        # Raise all errors at once
        if error_products:
            error_message = (
                "Bạn không được phép đặt quá số lượng hiện tại:"
                + "".join(error_products)
                + "\n\nVui lòng kiểm tra lại số lượng còn lại trong kho!"
            )
            raise ValidationError(error_message)

    def _handle_agency_discount(self):
        # Filter out orders that are returns
        non_return_orders = self.filtered(lambda order: not order.is_order_returns)

        # Filter out orders that are not by partner agency and compute discount
        non_return_orders.filtered(
            lambda order: order.partner_id.is_agency
        ).with_context(action_confirm=True).action_compute_discount()

    # =============================================================
    # TRIGGER Methods (Public)
    # These methods are called when a record is updated or deleted.
    # =============================================================

    def trigger_update(self):
        """=== This method is called when a record is updated or deleted ==="""
        if self._context.get("trigger_update", False):
            try:
                # Update the discount amount in the sale order
                # self._update_sale_order_discount_amount()

                # Update the partner's discount amount
                self._update_partner_discount_amount()
            except Exception as e:
                # Log any exceptions that occur
                _logger.error("Failed to trigger update recordset: %s", e)

    # def _update_sale_order_discount_amount(self):
    #     for order in self:
    #         print(f"Write your logic code here. {order.name_get()}")
    #
    #     return True

    def _update_partner_discount_amount(self):
        for order in self.filtered(
            lambda so: not so._is_order_returns()
            and so.partner_id.is_agency
            and so.bonus_order > 0
        ):
            try:
                # Calculate the total bonus
                total_bonus = order.partner_id.amount_currency - order.bonus_order

                # Update the partner's discount amount
                order.partner_id.write(
                    {"amount": total_bonus, "amount_currency": total_bonus}
                )
            except Exception as e:
                # Log any exceptions that occur
                _logger.error("Failed to update partner discount amount: %s", e)

        return True

    # ==================================
    # TOOLING
    # ==================================

    def field_exists(self, model_name, field_name):
        """
        Check if a field exists on the model.

        Args:
            model_name (str): The name of Model to check.
            field_name (str): The name of Field to check.

        Returns:
            bool: True if the field exists, False otherwise.
        """
        # Get the definition of each field on the model
        f = self.env[model_name].fields_get()

        # Check if the field name is in the keys of the fields dictionary
        return field_name in f.keys()

    def _is_order_returns(self):
        return self.is_order_returns
