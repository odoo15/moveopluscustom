# -*- coding: utf-8 -*-
import base64
import calendar
import io
import logging
import re
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

try:
    from odoo.tools.misc import xlsxwriter
except ImportError:
    import xlsxwriter

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.misc import format_date, formatLang, get_lang

_logger = logging.getLogger(__name__)

DEFAULT_SERVER_DATE_FORMAT = "%Y-%m-%d"
DEFAULT_SERVER_TIME_FORMAT = "%H:%M:%S"
DEFAULT_SERVER_DATETIME_FORMAT = "%s %s" % (
    DEFAULT_SERVER_DATE_FORMAT,
    DEFAULT_SERVER_TIME_FORMAT,
)

DISCOUNT_APPROVER = "mv_sale.group_mv_compute_discount_approver"

# Ticket Type Codes for Warranty Activation:
SUB_DEALER_CODE = "kich_hoat_bao_hanh_dai_ly"
END_USER_CODE = "kich_hoat_bao_hanh_nguoi_dung_cuoi"


def get_years():
    return [(str(i), str(i)) for i in range(2000, datetime.now().year + 1)]


def get_months():
    return [(str(i), str(i)) for i in range(1, 13)]


def convert_to_code(text):
    # Convert to lowercase
    text = text.lower()

    # Replace relational operators
    replacements = {
        "<=": "lower_and_equal",
        ">=": "greater_and_equal",
        "<": "lower_than",
        ">": "greater_than",
        "=": "equal",
    }

    for key, value in replacements.items():
        text = text.replace(key, value)

    # Replace spaces and other non-alphanumeric characters with underscores
    text = re.sub(r"\s+|[^a-zA-Z0-9]", "_", text)

    # Remove leading or trailing underscores
    text = text.strip("_")

    return text


class MvWarrantyDiscountPolicy(models.Model):
    _name = "mv.warranty.discount.policy"
    _description = _("Warranty Discount Policy")
    _order = "date_from desc, date_to desc"

    # ACCESS/RULE Fields:
    can_access = fields.Boolean(
        compute="_compute_can_access",
        default=lambda self: self.env.user.has_group(DISCOUNT_APPROVER)
        or self.env.user._is_admin()
        or self.env.user._is_system(),
    )

    @api.depends_context("uid")
    def _compute_can_access(self):
        for record in self:
            record.can_access = self._fully_access()

    active = fields.Boolean(string="Active", default=True)
    name = fields.Char(compute="_compute_name", store=True, readonly=False)
    date_from = fields.Date(default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date(
        default=lambda self: (date.today().replace(day=1) + timedelta(days=32)).replace(
            day=1
        )
        - timedelta(days=1)
    )
    policy_status = fields.Selection(
        selection=[
            ("open", "Sẵn sàng"),
            ("applying", "Đang Áp Dụng"),
            ("close", "Đã kết thúc"),
        ],
        default="open",
        string="Status",
    )
    product_attribute_ids = fields.Many2many("product.attribute")
    line_ids = fields.One2many(
        comodel_name="mv.warranty.discount.policy.line",
        inverse_name="warranty_discount_policy_id",
    )
    partner_ids = fields.Many2many(
        comodel_name="mv.discount.partner", domain=[("partner_id.is_agency", "=", True)]
    )

    def action_reset_to_open(self):
        self.ensure_one()

        if not self._fully_access():
            raise AccessError(
                "Bạn không có quyền thao tác, vui lòng liên hệ người có thẩm quyền!"
            )

        self.write({"policy_status": "open"})

    def action_apply(self):
        self.ensure_one()

        if not self._fully_access():
            raise AccessError(
                "Bạn không có quyền thao tác, vui lòng liên hệ người có thẩm quyền!"
            )

        if self.policy_status == "open":
            self.write({"policy_status": "applying"})

        return True

    def action_close(self):
        self.ensure_one()

        if not self._fully_access():
            raise AccessError(
                "Bạn không có quyền thao tác, vui lòng liên hệ người có thẩm quyền!"
            )

        if self.policy_status == "applying":
            self.write({"policy_status": "close"})

        return True

    @api.depends("date_from", "date_to")
    def _compute_name(self):
        for record in self:
            policy_name = "Chính sách chiết khấu kích hoạt"
            date_from = record.date_from
            date_to = record.date_to

            if date_from and date_to:
                if date_from.year == date_to.year:
                    if date_from.month == date_to.month:
                        record.name = (
                            f"{policy_name} (tháng {date_from.month}/{date_from.year})"
                        )
                    else:
                        record.name = f"{policy_name} (từ {date_from.month}/{date_from.year} đến {date_to.month}/{date_to.year})"
                else:
                    record.name = policy_name
            else:
                record.name = policy_name

    @api.onchange("date_from")
    def _onchange_date_from(self):
        if self.date_from:
            self.date_to = (self.date_from + timedelta(days=32)).replace(
                day=1
            ) - timedelta(days=1)

    @api.model_create_multi
    def create(self, vals_list):
        res = super(MvWarrantyDiscountPolicy, self).create(vals_list)

        # TODO: This method should be validated for every time create new record
        if res:
            for record in res:
                if not record.partner_ids:
                    partner_ids = self.env["mv.discount.partner"].search(
                        [("partner_id.is_agency", "=", True)]
                    )
                    record.partner_ids = [(6, 0, partner_ids.ids)]
                    for partner in partner_ids:
                        partner.write(
                            {"warranty_discount_policy_ids": [(4, record.id)]}
                        )

        return res

    def write(self, vals):
        res = super(MvWarrantyDiscountPolicy, self).write(vals)

        # TODO: This method should be validated for every time update current record
        if res:
            for record in self:
                if record.partner_ids:
                    for partner in record.partner_ids:
                        partner.write(
                            {"warranty_discount_policy_ids": [(6, 0, record.ids)]}
                        )

        return res

    @api.constrains("line_ids")
    def _limit_policy_conditions(self):
        for record in self:
            if len(record.line_ids) > 3:
                raise ValidationError(
                    _("Chính sách chiết khấu không được nhiều hơn 3 điều kiện!")
                )

    # =================================
    # CONSTRAINS Methods
    # =================================

    @api.constrains("date_from", "date_to")
    def _validate_already_exist_policy(self):
        for record in self:
            if record.date_from and record.date_to:
                record_exists = self.env["mv.warranty.discount.policy"].search_count(
                    [
                        ("id", "!=", record.id),
                        ("active", "=", True),
                        ("date_from", ">=", record.date_from),
                        ("date_to", "<=", record.date_to),
                    ]
                )
                if record_exists > 0:
                    raise ValidationError(
                        _("Chính sách này đã bị trùng, vui lòng kiểm tra lại!")
                    )

    # =================================
    # HELPER / PRIVATE Methods
    # =================================

    def _fully_access(self):
        access = (
            self.env.user.has_group(DISCOUNT_APPROVER)
            or self.env.user._is_admin()
            or self.env.user._is_system()
        )
        return access


class MvWarrantyDiscountPolicyLine(models.Model):
    _name = _description = "mv.warranty.discount.policy.line"
    _rec_name = "explanation"

    sequence = fields.Integer(required=True, default=1)
    warranty_discount_policy_id = fields.Many2one(
        comodel_name="mv.warranty.discount.policy",
        domain=[("active", "=", True)],
        readonly=True,
        help="Parent Model: mv.warranty.discount.policy",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency", default=lambda self: self.env.company.currency_id
    )
    quantity_from = fields.Integer("Số lượng Min", default=0)
    quantity_to = fields.Integer("Số lượng Max", default=0)
    discount_amount = fields.Monetary(
        "Số tiền chiết khấu", digits=(16, 2), currency_field="currency_id"
    )
    explanation = fields.Text("Diễn giải")
    explanation_code = fields.Char(
        "Diễn giải (Code)", compute="_compute_explanation_code", store=True
    )

    @api.depends("explanation")
    def _compute_explanation_code(self):
        for record in self:
            if record.explanation:
                record.explanation_code = convert_to_code(record.explanation)
            else:
                record.explanation_code = "_code_"


class MvComputeWarrantyDiscountPolicy(models.Model):
    _inherit = ["mail.thread"]
    _name = "mv.compute.warranty.discount.policy"
    _description = _("Compute Warranty Discount Policy")

    def _do_readonly(self):
        for rec in self:
            if rec.state in ["done"]:
                rec.do_readonly = True
            else:
                rec.do_readonly = False

    # ACCESS / RULE Fields:
    do_readonly = fields.Boolean("Readonly?", compute="_do_readonly")

    @api.depends("month", "year")
    def _compute_name(self):
        for rec in self:
            if rec.month and rec.year:
                rec.name = "{}/{}".format(str(rec.month), str(rec.year))
            else:
                dt = datetime.now().replace(day=1)
                rec.name = "{}/{}".format(str(dt.month), str(dt.year))

    # BASE Fields:
    month = fields.Selection(get_months())
    year = fields.Selection(get_years(), default=str(datetime.now().year))
    compute_date = fields.Datetime(compute="_compute_compute_date", store=True)
    name = fields.Char(compute="_compute_name", store=True)
    state = fields.Selection(
        selection=[("draft", "Nháp"), ("confirm", "Lưu"), ("done", "Đã Duyệt")],
        default="draft",
        readonly=True,
        tracking=True,
    )
    # RELATION Fields:
    warranty_discount_policy_id = fields.Many2one(
        comodel_name="mv.warranty.discount.policy",
        domain=[("active", "=", True), ("policy_status", "=", "applying")],
        help="Parent Model: mv.warranty.discount.policy",
    )
    line_ids = fields.One2many("mv.compute.warranty.discount.policy.line", "parent_id")

    @api.depends("year", "month")
    def _compute_compute_date(self):
        for rec in self:
            if rec.month and rec.year:
                rec.compute_date = datetime.now().replace(
                    day=1, month=int(rec.month), year=int(rec.year)
                )
            else:
                rec.compute_date = datetime.now().replace(day=1)

    # =================================
    # BUSINESS Methods
    # =================================

    def action_reset_to_draft(self):
        """
        Resets the state of the current record to 'draft'.
        """
        try:
            self.ensure_one()
            if self.state != "draft":
                self.state = "draft"
                self.line_ids = [(5, 0, 0)]  # Remove all lines
        except Exception as e:
            _logger.error("Failed to reset to draft: %s", e)
            pass

    def action_done(self):
        if not self._access_approve():
            raise AccessError(_("Bạn không có quyền duyệt!"))

        for rec in self.filtered(lambda r: len(r.line_ids) > 0):
            for line in rec.line_ids:
                self.env["res.partner"].sudo().browse(
                    line.partner_id.id
                ).action_update_discount_amount()
                line.helpdesk_ticket_product_moves_ids.mapped(
                    "helpdesk_ticket_id"
                ).write(
                    {
                        "stage_id": self.env["helpdesk.stage"]
                        .search(
                            [
                                (
                                    "id",
                                    "=",
                                    self.env.ref(
                                        "mv_website_helpdesk.warranty_stage_done"
                                    ).id,
                                )
                            ],
                            limit=1,
                        )
                        .id
                    }
                )
            rec.state = "done"

    def action_reset(self):
        if self.state == "confirm":
            self.action_reset_to_draft()

    def action_calculate_discount_line(self):
        self.ensure_one()

        if not self.warranty_discount_policy_id:
            raise ValidationError("Chưa chọn Chính sách chiết khấu!")

        # Fetch all ticket with conditions at once
        tickets = self._fetch_tickets()
        if not tickets:
            raise UserError(
                "Hiện tại không có phiếu nào đã kích hoạt trong tháng {}/{}".format(
                    self.month, self.year
                )
            )

        # Get ticket has product move by [tickets]
        ticket_product_moves = self._fetch_ticket_product_moves(tickets)

        # Fetch partners at once
        partners = self._fetch_partners(ticket_product_moves)
        if not partners:
            raise UserError(
                "Không tìm thấy Đại lý đăng ký trong tháng {}/{}".format(
                    self.month, self.year
                )
            )

        # Calculate discount lines
        results = self._calculate_discount_lines(partners, ticket_product_moves)
        if not results:
            raise UserError(
                "Không có dữ liệu để tính chiết khấu cho tháng {}/{}".format(
                    self.month, self.year
                )
            )

        self.write({"line_ids": results, "state": "confirm"})

    def _prepare_values_to_calculate_discount(self, partner, compute_date):
        self.ensure_one()
        return {
            "parent_id": self.id,
            "parent_compute_date": compute_date,
            "partner_id": partner.id,
            "currency_id": partner.company_id.sudo().currency_id.id
            or self.env.company.sudo().currency_id.id,
            "helpdesk_ticket_product_moves_ids": [],
            "product_activation_count": 0,
            "first_warranty_policy_requirement_id": False,
            "first_count": 0,
            "first_quantity_from": 0,
            "first_quantity_to": 0,
            "first_warranty_policy_money": 0,
            "first_warranty_policy_total_money": 0,
            "second_warranty_policy_requirement_id": False,
            "second_count": 0,
            "second_quantity_from": 0,
            "second_quantity_to": 0,
            "second_warranty_policy_money": 0,
            "second_warranty_policy_total_money": 0,
            "third_warranty_policy_requirement_id": False,
            "third_count": 0,
            "third_quantity_from": 0,
            "third_quantity_to": 0,
            "third_warranty_policy_money": 0,
            "third_warranty_policy_total_money": 0,
        }

    def _calculate_discount_lines(self, partners, ticket_product_moves):
        results = []
        policy_used = self.warranty_discount_policy_id
        compute_date = self.compute_date

        for partner in partners.filtered(
            lambda p: p.is_agency
            and p.id in policy_used.partner_ids.mapped("partner_id").ids
        ):
            # Prepare values to calculate discount
            vals = self._prepare_values_to_calculate_discount(partner, compute_date)

            code_registered = []
            partner_tickets_registered = ticket_product_moves.filtered(
                lambda t: t.partner_id.id == partner.id
                or t.partner_id.parent_id.id == partner.id
            )
            for ticket in partner_tickets_registered:
                if ticket.lot_name not in [
                    x[0] for x in code_registered
                ] or ticket.qr_code not in [x[1] for x in code_registered]:
                    code_registered.append((ticket.lot_name, ticket.qr_code))
                    vals["helpdesk_ticket_product_moves_ids"] += ticket.ids
                else:
                    ticket.write({"product_activate_twice": True})
                    vals["helpdesk_ticket_product_moves_ids"] += ticket.ids

            vals["product_activation_count"] = len(list(set(code_registered)))

            product_tmpl = self._fetch_product_template(
                partner_tickets_registered.mapped("product_id.product_tmpl_id")
            )
            product_tmpl_attribute_values = (
                self._fetch_product_template_attribute_values(product_tmpl)
            )
            product_attribute_values = self._fetch_product_attribute_values(
                policy_used, product_tmpl_attribute_values
            )

            context_lines = dict(self.env.context or {})

            # ========= First Condition Warranty Policy =========
            first_count = 0
            first_policy_code = (
                context_lines.get("first_policy_code") or "rim_lower_and_equal_16"
            )
            first_warranty_policy = self._fetch_warranty_policy(first_policy_code)
            vals["first_warranty_policy_requirement_id"] = first_warranty_policy.id
            vals["first_quantity_from"] = first_warranty_policy.quantity_from
            vals["first_quantity_to"] = first_warranty_policy.quantity_to
            vals["first_warranty_policy_money"] = (
                first_warranty_policy.discount_amount or 0
            )
            # ========= Second Condition Warranty Policy =========
            second_count = 0
            second_policy_code = (
                context_lines.get("second_policy_code") or "rim_greater_and_equal_17"
            )
            second_warranty_policy = self._fetch_warranty_policy(second_policy_code)
            vals["second_warranty_policy_requirement_id"] = second_warranty_policy.id
            vals["second_quantity_from"] = second_warranty_policy.quantity_from
            vals["second_quantity_to"] = second_warranty_policy.quantity_to
            vals["second_warranty_policy_money"] = (
                second_warranty_policy.discount_amount or 0
            )
            # ========= Third Condition Warranty Policy =========
            third_count = 0
            third_policy_code = context_lines.get("third_policy_code") or None
            third_warranty_policy = self._fetch_warranty_policy(
                third_policy_code,
                [
                    ("sequence", "=", 3),
                    (
                        "explanation_code",
                        "not in",
                        [first_policy_code, second_policy_code],
                    ),
                ],
            )
            vals["third_warranty_policy_requirement_id"] = third_warranty_policy.id
            vals["third_quantity_from"] = third_warranty_policy.quantity_from
            vals["third_quantity_to"] = third_warranty_policy.quantity_to
            vals["third_warranty_policy_money"] = (
                third_warranty_policy.discount_amount or 0
            )

            for attribute in product_attribute_values:
                # ========= First Condition (Product has RIM <= 16) =========
                if float(attribute.name) <= float(first_warranty_policy.quantity_to):
                    first_count += 1
                # ========= Second Condition (Product has RIM >= 17) =========
                elif float(attribute.name) >= float(
                    first_warranty_policy.quantity_from
                ):
                    second_count += 1

            vals["first_count"] = first_count
            vals["first_warranty_policy_total_money"] = (
                first_warranty_policy.discount_amount * first_count
            )
            vals["second_count"] = second_count
            vals["second_warranty_policy_total_money"] = (
                second_warranty_policy.discount_amount * second_count
            )

            results.append((0, 0, vals))

        return results

    def _fetch_tickets(self):
        try:
            date_from, date_to = self._get_dates(
                self.compute_date, self.month, self.year
            )

            # Cache the stage references to avoid multiple lookups
            stage_new_id = self.env.ref("mv_website_helpdesk.warranty_stage_new").id
            stage_done_id = self.env.ref("mv_website_helpdesk.warranty_stage_done").id

            # Define the domain for search
            domain = [
                ("helpdesk_ticket_product_move_ids", "!=", False),
                ("ticket_type_id.code", "in", [SUB_DEALER_CODE, END_USER_CODE]),
                ("stage_id", "in", [stage_new_id, stage_done_id]),
                ("create_date", ">=", date_from),
                ("create_date", "<", date_to),
            ]

            # Perform the search
            return self.env["helpdesk.ticket"].search(domain)

        except ValueError as ve:
            _logger.error(f"Value error in fetching tickets: {ve}")
        except self.env["helpdesk.ticket"]._exceptions.AccessError as ae:
            _logger.error(f"Access error in fetching tickets: {ae}")
        except Exception as e:
            _logger.error(f"Unexpected error in fetching tickets: {e}")

        # Return an empty recordset in case of an error
        return self.env["helpdesk.ticket"]

    def _fetch_ticket_product_moves(self, tickets):
        if not tickets:
            return self.env["mv.helpdesk.ticket.product.moves"]

        try:
            return self.env["mv.helpdesk.ticket.product.moves"].search(
                [
                    ("helpdesk_ticket_id", "in", tickets.ids),
                    ("product_activate_twice", "=", False),
                ]
            )
        except Exception as e:
            _logger.error(f"Failed to fetch ticket product moves: {e}")
            return self.env["mv.helpdesk.ticket.product.moves"]

    def _fetch_partners(self, ticket_product_moves):
        try:
            if ticket_product_moves:
                return (
                    self.env["res.partner"]
                    .sudo()
                    .browse(ticket_product_moves.mapped("partner_id").ids)
                )
        except Exception as e:
            _logger.error(f"Failed to fetch partners: {e}")
            return self.env["res.partner"]

    def _fetch_warranty_policy(self, policy_code, domain=[]):
        try:
            policy_domain = domain
            if policy_code and not domain:
                policy_domain = [("explanation_code", "=", policy_code)]

            return self.env["mv.warranty.discount.policy.line"].search(
                policy_domain, limit=1
            )
        except Exception as e:
            _logger.error(f"Failed to fetch warranty policy: {e}")
            return self.env["mv.warranty.discount.policy.line"]

    def _fetch_product_template(self, products):
        try:
            if products:
                return self.env["product.template"].search([("id", "in", products.ids)])
        except Exception as e:
            _logger.error(f"Failed to fetch product template: {e}")
            return False

    def _fetch_product_template_attribute_values(self, products):
        try:
            if products:
                return self.env["product.template.attribute.value"].search(
                    [("product_tmpl_id", "in", products.ids)]
                )
        except Exception as e:
            _logger.error(f"Failed to fetch product template attribute values: {e}")
            return self.env["product.template.attribute.value"]

    def _fetch_product_attribute_values(self, policy_used, products):
        try:
            if products and policy_used:
                return self.env["product.attribute.value"].search(
                    [
                        (
                            "id",
                            "in",
                            products.mapped("product_attribute_value_id")
                            .filtered(
                                lambda v: v.attribute_id.id
                                in policy_used.product_attribute_ids.ids
                            )
                            .ids,
                        )
                    ]
                )
        except Exception as e:
            _logger.error(f"Failed to fetch product attribute values: {e}")
            return self.env["product.attribute.value"]

    # =================================
    # ORM Methods
    # =================================

    def unlink(self):
        self._validate_policy_done_not_unlink()
        return super(MvComputeWarrantyDiscountPolicy, self).unlink()

    # =================================
    # CONSTRAINS / VALIDATION Methods
    # =================================

    def _validate_policy_done_not_unlink(self):
        for rec in self:
            if rec.state == "done":
                raise UserError(
                    f"Phần tính toán chiết khấu cho tháng {rec.month}/{rec.year} đã được Duyệt. Không thể xoá! "
                )

    @api.constrains("warranty_discount_policy_id", "month", "year")
    def _validate_discount_policy_already_exist(self):
        for record in self:
            if record.warranty_discount_policy_id and record.month and record.year:
                record_exists = self.env[
                    "mv.compute.warranty.discount.policy"
                ].search_count(
                    [
                        ("id", "!=", record.id),
                        (
                            "warranty_discount_policy_id",
                            "=",
                            record.warranty_discount_policy_id.id,
                        ),
                        ("month", "=", record.month),
                        ("year", "=", record.year),
                    ]
                )
                if record_exists > 0:
                    raise ValidationError(
                        f"Chính sách của {record.month}/{record.year} đã được tạo hoặc đã được tính toán rồi!"
                    )

    @api.constrains(
        "compute_date",
        "warranty_discount_policy_id.date_from",
        "warranty_discount_policy_id.date_to",
    )
    def _validate_time_frame_of_discount_policy(self):
        for record in self:
            if record.warranty_discount_policy_id and record.compute_date:
                policy = record.warranty_discount_policy_id
                if not policy.date_from <= record.compute_date.date() <= policy.date_to:
                    raise ValidationError(
                        "Tháng cần tính toán phải nằm trong khoảng thời gian quy định của chính sách!"
                    )

    # =================================
    # HELPER / PRIVATE Methods
    # =================================

    def _get_dates(self, report_date, month, year):
        """
        Computes the start and end dates of a given month and year.

        Args:
            month (str): The target month.
            year (str): The target year.

        Returns:
            tuple: A tuple containing the start and end dates of the given month and year.
        """
        try:
            # Compute date_from
            date_from = report_date.replace(
                day=1,
                month=int(month),
                year=int(year),
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )

            # Compute date_to by adding one month and then subtracting one day
            date_to = date_from + relativedelta(months=1)

            return date_from, date_to
        except Exception as e:
            _logger.error("Failed to compute dates: %s", e)
            return None, None

    def _access_approve(self):
        return self.env.user.has_group(DISCOUNT_APPROVER)

    # =================================
    # REPORT Action/Data
    # =================================

    # TODO: Update report feature for the Compute Warranty Discount Policy

    @api.model
    def format_value(self, amount, currency=False, blank_if_zero=False):
        """Format amount to have a monetary display (with a currency symbol).
        E.g: 1000 => 1000.0 $

        :param amount:          A number.
        :param currency:        An optional res.currency record.
        :param blank_if_zero:   An optional flag forcing the string to be empty if amount is zero.
        :return:                The formatted amount as a string.
        """
        currency_id = currency or self.env.company.currency_id
        if currency_id.is_zero(amount):
            if blank_if_zero:
                return ""
            # don't print -0.0 in reports
            amount = abs(amount)

        if self.env.context.get("no_format"):
            return amount
        return formatLang(self.env, amount, currency_obj=currency_id)

    def _get_compute_discount_detail_data(self, report_date, pass_security=False):
        report_lines = []
        self.env["mv.compute.discount.line"].flush_model()
        query = """
                SELECT ROW_NUMBER() OVER ()                    AS row_index,
                           partner.name                            AS sub_dealer,
                           cdl.level                               AS level,
                           cdl.quantity_from                       AS quantity_from,
                           cdl.quantity                            AS quantity,
                           cdl.quantity_discount                   AS quantity_discount,
                           cdl.amount_total                        AS total,
                           cdl.month_money                         AS month_money,
                           cdl.two_money                           AS two_money,
                           cdl.quarter_money                       AS quarter_money,
                           cdl.year_money                          AS year_money,
                           COALESCE(cdl.promote_discount_money, 0) AS promote_discount_money,
                           cdl.total_money                         AS total_money
                FROM mv_compute_discount_line cdl
                    JOIN res_partner partner ON partner.id = cdl.partner_id
                WHERE cdl.parent_id = %s;
            """
        self.env.cr.execute(query, [self.id])
        for data in self.env.cr.dictfetchall():
            report_lines.append(
                {
                    "index": data["row_index"],
                    "partner_id": data["sub_dealer"],
                    "level": data["level"],
                    "quantity_from": data["quantity_from"],
                    "quantity": data["quantity"],
                    "quantity_discount": data["quantity_discount"],
                    "amount_total": data["total"],
                    "amount_month_money": data["month_money"],
                    "amount_two_money": data["two_money"],
                    "amount_quarter_money": data["quarter_money"],
                    "amount_year_money": data["year_money"],
                    "amount_promote_discount_money": data["promote_discount_money"],
                    "amount_total_money": data["total_money"],
                }
            )
        return report_lines

    def print_report(self):
        months = set(self.mapped("month"))

        if len(months) > 1:
            raise UserError(_("Only export report in ONE MONTH!"))

        # DOWNLOAD Report Data
        file_content, file_name = self.export_to_excel()

        # REMOVE All Excel Files by file_content:
        attachments_to_remove = self.env["ir.attachment"].search(
            [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
                ("create_uid", "=", self.env.uid),
                ("create_date", "<", fields.Datetime.now()),
                ("name", "ilike", "Moveoplus-Partners-Discount-Detail%"),
            ]
        )
        if attachments_to_remove:
            attachments_to_remove.unlink()

        # NEW Attachment to download
        new_attachment = (
            self.with_context(ats_penalties_fines=True)
            .env["ir.attachment"]
            .create(
                {
                    "name": file_name,
                    "description": file_name,
                    "datas": base64.b64encode(file_content),
                    "res_model": self._name,
                    "res_id": self.ids[0],
                }
            )
        )

        if len(new_attachment) == 1:
            return {
                "type": "ir.actions.act_url",
                "url": f"/web/content/{new_attachment[0].id}?download=true",
                "target": "self",
            }

        return False

    def export_to_excel(self):
        self.ensure_one()

        if not self:
            raise UserError(_("No data to generate the report for."))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        sheet = workbook.add_worksheet(
            "Discount in {}-{}".format(self.report_date.month, self.report_date.year)
        )
        file_name = "Moveoplus-Partners-Discount-Detail_%s-%s.xlsx" % (
            self.report_date.month,
            self.report_date.year,
        )
        data_lines = self._get_compute_discount_detail_data(False, False)

        # ############# [SETUP] #############
        base_format = {
            "bold": True,
            "font_name": "Arial",
            "font_size": 11,
            "align": "center",
            "valign": "vcenter",
            "border": True,
            "border_color": "black",
        }
        DEFAULT_FORMAT = workbook.add_format(base_format)

        # ############# [HEADER] #############
        sheet.set_row(0, 30)

        # ////// NAME = "Chi tiết chiết khấu của Đại Lý trong tháng {month/year}"
        sheet.merge_range("A1:M1", "", DEFAULT_FORMAT)
        format_first_title = [
            "Chi tiết chiết khấu của Đại Lý trong tháng ",
            workbook.add_format(
                {"font_name": "Arial", "font_size": 11, "color": "red", "bold": True}
            ),
            "{}/{}".format(self.month, self.year),
        ]
        sheet.write_rich_string(
            "A1",
            *format_first_title,
            DEFAULT_FORMAT,
        )

        SUB_TITLE_FORMAT = workbook.add_format(
            {
                "font_name": "Arial",
                "font_size": 10,
                "align": "center",
                "valign": "vcenter",
                "border": True,
                "border_color": "black",
                "bold": True,
                "bg_color": "#71C671",
                "text_wrap": True,
            }
        )

        SUB_TITLE_TOTAL_FORMAT = workbook.add_format(
            {
                "font_name": "Arial",
                "font_size": 10,
                "align": "center",
                "valign": "vcenter",
                "border": True,
                "border_color": "black",
                "bold": True,
                "bg_color": "#FFA07A",
                "text_wrap": True,
            }
        )

        # ////// NAME = "Thứ tự"
        sheet.merge_range("A2:A3", "", DEFAULT_FORMAT)
        sheet.write("A2", "#", SUB_TITLE_FORMAT)

        sheet.set_column(1, 0, 3)

        # ////// NAME = "Đại lý"
        sheet.merge_range("B2:B3", "", DEFAULT_FORMAT)
        sheet.write("B2", "Đại lý", SUB_TITLE_FORMAT)

        sheet.set_column(1, 1, 70)

        # ////// NAME = "Cấp bậc"
        sheet.merge_range("C2:C3", "", DEFAULT_FORMAT)
        sheet.write("C2", "Cấp bậc", SUB_TITLE_FORMAT)

        # ////// NAME = "24TA"
        sheet.merge_range("D2:D3", "", DEFAULT_FORMAT)
        sheet.write("D2", "24TA", SUB_TITLE_FORMAT)

        # ////// NAME = "Số lượng lốp đã bán (Cái)"
        sheet.merge_range("E2:E3", "", DEFAULT_FORMAT)
        sheet.write("E2", "SL lốp đã bán (Cái)", SUB_TITLE_FORMAT)

        # ////// NAME = "Số lượng lốp Khuyến Mãi (Cái)"
        sheet.merge_range("F2:F3", "", DEFAULT_FORMAT)
        sheet.write("F2", "SL lốp khuyến mãi (Cái)", SUB_TITLE_FORMAT)

        # ////// NAME = "Doanh thu Tháng"
        sheet.merge_range("G2:G3", "", DEFAULT_FORMAT)
        sheet.write("G2", "Doanh thu", SUB_TITLE_TOTAL_FORMAT)

        # ////// NAME = "Số tiền chiết khấu tháng"
        sheet.merge_range("H2:H3", "", DEFAULT_FORMAT)
        sheet.write("H2", "Tiền CK Tháng", SUB_TITLE_TOTAL_FORMAT)

        # ////// NAME = "Số tiền chiết khấu 2 tháng"
        sheet.merge_range("I2:I3", "", DEFAULT_FORMAT)
        sheet.write("I2", "Tiền CK 2 Tháng", SUB_TITLE_TOTAL_FORMAT)

        # ////// NAME = "Số tiền chiết khấu quý"
        sheet.merge_range("J2:J3", "", DEFAULT_FORMAT)
        sheet.write("J2", "Tiền CK Quý", SUB_TITLE_TOTAL_FORMAT)

        # ////// NAME = "Số tiền chiết khấu năm"
        sheet.merge_range("K2:K3", "", DEFAULT_FORMAT)
        sheet.write("K2", "Tiền CK Năm", SUB_TITLE_TOTAL_FORMAT)

        # ////// NAME = "Số tiền chiết khấu khuyến khích"
        sheet.merge_range("L2:L3", "", DEFAULT_FORMAT)
        sheet.write("L2", "Tiền CK Khuyến Khích", SUB_TITLE_TOTAL_FORMAT)

        # ////// NAME = "Tổng tiền chiết khấu"
        sheet.merge_range("M2:M3", "", DEFAULT_FORMAT)
        sheet.write("M2", "Tổng tiền", SUB_TITLE_TOTAL_FORMAT)

        sheet.set_column(4, 12, 15)

        # ############# [BODY] #############
        BODY_CHAR_FORMAT = workbook.add_format(
            {
                "font_name": "Arial",
                "font_size": 10,
                "valign": "vcenter",
                "border": True,
                "border_color": "black",
            }
        )
        BODY_NUM_FORMAT = workbook.add_format(
            {
                "font_name": "Arial",
                "font_size": 10,
                "align": "center",
                "valign": "vcenter",
                "border": True,
                "border_color": "black",
            }
        )
        BODY_TOTAL_NUM_FORMAT = workbook.add_format(
            {
                "font_name": "Arial",
                "font_size": 10,
                "align": "right",
                "valign": "vcenter",
                "border": True,
                "border_color": "black",
                "num_format": "#,##0.00",
            }
        )

        column_headers = list(data_lines[0].keys())
        for count, data in enumerate(data_lines, start=3):
            for col, key in enumerate(column_headers):
                if isinstance(data[key], str):
                    sheet.write(count, col, data[key], BODY_CHAR_FORMAT)
                elif isinstance(data[key], int) or isinstance(data[key], float):
                    if col in [6, 7, 8, 9, 10, 11, 12]:
                        sheet.write(count, col, data[key], BODY_TOTAL_NUM_FORMAT)
                    else:
                        sheet.write(count, col, data[key], BODY_NUM_FORMAT)
                else:
                    sheet.write(count, col, data[key])

        # ############# [FOOTER] ###########################################

        workbook.close()
        output.seek(0)

        return output.read(), file_name.replace("-", "_")


class MvComputeWarrantyDiscountPolicyLine(models.Model):
    _name = _description = "mv.compute.warranty.discount.policy.line"

    def _get_company_currency(self):
        for rec in self:
            company = rec.partner_id.company_id or self.env.company
            rec.currency_id = company.sudo().currency_id

    currency_id = fields.Many2one(
        "res.currency", compute="_get_company_currency", store=True
    )
    parent_id = fields.Many2one(
        "mv.compute.warranty.discount.policy",
        domain=[("active", "=", True)],
        readonly=True,
        help="Parent Model: mv.compute.warranty.discount.policy",
    )
    parent_name = fields.Char("Name", compute="_compute_parent_name", store=True)
    parent_compute_date = fields.Datetime(readonly=True)
    parent_state = fields.Selection(related="parent_id.state", readonly=True)
    partner_id = fields.Many2one("res.partner", readonly=True)
    helpdesk_ticket_product_moves_ids = fields.Many2many(
        "mv.helpdesk.ticket.product.moves",
        "compute_warranty_discount_policy_ticket_product_moves_rel",
        readonly=True,
        context={"create": False, "edit": False},
    )
    product_activation_count = fields.Integer(default=0)
    first_warranty_policy_requirement_id = fields.Many2one(
        "mv.warranty.discount.policy.line", readonly=True
    )
    first_count = fields.Integer()
    first_quantity_from = fields.Integer()
    first_quantity_to = fields.Integer()
    first_warranty_policy_money = fields.Monetary(
        digits=(16, 2), currency_field="currency_id"
    )
    first_warranty_policy_total_money = fields.Monetary(
        digits=(16, 2), currency_field="currency_id"
    )
    second_warranty_policy_requirement_id = fields.Many2one(
        "mv.warranty.discount.policy.line", readonly=True
    )
    second_count = fields.Integer()
    second_quantity_from = fields.Integer()
    second_quantity_to = fields.Integer()
    second_warranty_policy_money = fields.Monetary(
        digits=(16, 2), currency_field="currency_id"
    )
    second_warranty_policy_total_money = fields.Monetary(
        digits=(16, 2), currency_field="currency_id"
    )
    third_warranty_policy_requirement_id = fields.Many2one(
        "mv.warranty.discount.policy.line", readonly=True
    )
    third_count = fields.Integer()
    third_quantity_from = fields.Integer()
    third_quantity_to = fields.Integer()
    third_warranty_policy_money = fields.Monetary(
        digits=(16, 2), currency_field="currency_id"
    )
    third_warranty_policy_total_money = fields.Monetary(
        digits=(16, 2), currency_field="currency_id"
    )
    total_amount_currency = fields.Monetary(
        compute="_compute_total",
        store=True,
        digits=(16, 2),
        currency_field="currency_id",
    )

    @api.depends("parent_compute_date")
    def _compute_parent_name(self):
        for rec in self:
            if rec.parent_compute_date:
                rec.parent_name = "{}/{}".format(
                    str(rec.parent_compute_date.month),
                    str(rec.parent_compute_date.year),
                )
            else:
                dt = datetime.now().replace(day=1)
                rec.parent_name = "{}/{}".format(str(dt.month), str(dt.year))

    @api.depends(
        "first_warranty_policy_total_money",
        "second_warranty_policy_total_money",
        "third_warranty_policy_total_money",
    )
    def _compute_total(self):
        for rec in self:
            rec.total_amount_currency = (
                rec.first_warranty_policy_total_money
                + rec.second_warranty_policy_total_money
                + rec.third_warranty_policy_total_money
            )
