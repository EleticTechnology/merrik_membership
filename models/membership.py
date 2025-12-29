from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date
from dateutil.relativedelta import relativedelta
import uuid
import base64


class MerrikhMembership(models.Model):
    _name = "merrikh.membership"
    _description = "Merrikh Membership"
    _inherit = ["mail.thread", "mail.activity.mixin", "portal.mixin"]
    _order = "create_date desc"

    # =========================
    # BASIC FIELDS
    # =========================
    sequence = fields.Char(
        string="Membership No",
        default="New",
        readonly=True,
        copy=False,
        tracking=True,
    )

    access_token = fields.Char("Access Token")

    name = fields.Char(string="Full Name", required=True)
    phone = fields.Char(required=True)
    email = fields.Char()
    nationality = fields.Char()
    id_number = fields.Char(string="ID / Passport No", required=True)
    birth_date = fields.Date(string="Birth Date")
    uae_id_number = fields.Char(string="UAE ID Number")
    job_title = fields.Char(string="Job Title")
    address = fields.Char(string="Address")
    uae_id_image = fields.Image(string="UAE ID Image")

    image = fields.Image()
    id_image = fields.Image()

    accept_terms = fields.Boolean(default=False)
    terms_text = fields.Text(readonly=True)

    partner_id = fields.Many2one("res.partner", index=True)

    # =========================
    # MEMBERSHIP TYPE
    # =========================
    membership_type = fields.Selection(
        [
            ("monthly", "عضوية شهرية (20 درهم)"),
            ("semiannual", "عضوية 6 أشهر (120 درهم)"),
            ("annual", "عضوية سنوية (240 درهم)"),
        ],
        default="monthly",
        required=True,
        tracking=True,
    )

    amount = fields.Float(
        string="المبلغ (درهم)",
        compute="_compute_amount",
        store=True,
    )

    state = fields.Selection(
        [
            ("draft", "New"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("invoiced", "Invoiced"),
            ("paid", "Paid"),
            ("active", "Active"),
            ("expired", "Expired"),
        ],
        default="draft",
        tracking=True,
    )

    start_date = fields.Date()
    end_date = fields.Date()
    last_invoice_date = fields.Date(string="آخر فاتورة", readonly=True)

    invoice_id = fields.Many2one("account.move", copy=False)
    verify_uuid = fields.Char(readonly=True, index=True)

    # =========================
    # COMPUTE AMOUNT
    # =========================
    @api.depends("membership_type")
    def _compute_amount(self):
        for rec in self:
            if rec.membership_type == "monthly":
                rec.amount = 20
            elif rec.membership_type == "semiannual":
                rec.amount = 120
            elif rec.membership_type == "annual":
                rec.amount = 240
            else:
                rec.amount = 0

    # =========================
    # CREATE
    # =========================
    @api.model
    def create(self, vals):
        if vals.get("sequence", "New") == "New":
            vals["sequence"] = (
                self.env["ir.sequence"].next_by_code("merrikh.membership") or "New"
            )

        rec = super().create(vals)

        rec.verify_uuid = str(uuid.uuid4())
        rec._portal_ensure_token()

        if not rec.partner_id:
            rec.partner_id = rec._create_or_link_partner()

        if rec.accept_terms and not rec.terms_text:
            rec.terms_text = rec._default_terms_text()

        return rec

    # =========================
    # PARTNER
    # =========================
    def _create_or_link_partner(self):
        self.ensure_one()
        Partner = self.env["res.partner"].sudo()

        partner = False
        if self.email:
            partner = Partner.search([("email", "=", self.email)], limit=1)

        if partner:
            partner.write({
                "name": self.name,
                "phone": self.phone,
                "email": self.email,
            })
            return partner.id

        return Partner.create({
            "name": self.name,
            "phone": self.phone,
            "email": self.email,
            "type": "contact",
        }).id

    # =========================
    # ACTIONS
    # =========================
    def action_approve(self):
        for rec in self:
            if rec.state != "draft":
                continue

            rec.state = "approved"
            rec._ensure_portal_user()
            rec.action_create_invoice()

    def action_reject(self):
        for rec in self:
            if rec.state in ("paid", "active"):
                raise UserError(_("You cannot reject a paid or active membership."))
            rec.state = "rejected"

    # =========================
    # CREATE INVOICE
    # =========================
    def action_create_invoice(self):
        for rec in self:
            if rec.state not in ("approved", "active"):
                continue

            product_map = {
                "monthly": "merrikh_membership.product_membership_monthly",
                "semiannual": "merrikh_membership.product_membership_semiannual",
                "annual": "merrikh_membership.product_membership_annual",
            }

            product = self.env.ref(
                product_map.get(rec.membership_type),
                raise_if_not_found=False,
            )

            if not product:
                raise UserError(_("Membership product not found."))

            invoice = self.env["account.move"].sudo().create({
                "move_type": "out_invoice",
                "partner_id": rec.partner_id.id,
                "invoice_line_ids": [
                    (0, 0, {
                        "product_id": product.id,
                        "name": product.name,
                        "quantity": 1,
                        "price_unit": rec.amount,
                    })
                ],
                "invoice_origin": rec.sequence,
            })

            invoice.action_post()
            rec.invoice_id = invoice.id
            rec.state = "invoiced"
            rec.last_invoice_date = date.today()

    # =========================
    # CHECK PAYMENT
    # =========================
    def action_check_payment_and_activate(self):
        for rec in self:
            if rec.invoice_id and rec.invoice_id.payment_state in ("paid", "in_payment"):
                rec.state = "paid"
                rec._activate_membership()

    # =========================
    # ACTIVATE MEMBERSHIP
    # =========================
    def _activate_membership(self):
        self.ensure_one()

        if not self.start_date:
            self.start_date = date.today()

        if self.membership_type == "monthly":
            self.end_date = self.start_date + relativedelta(months=1)
        elif self.membership_type == "semiannual":
            self.end_date = self.start_date + relativedelta(months=6)
        elif self.membership_type == "annual":
            self.end_date = self.start_date + relativedelta(years=1)

        self.state = "active"

        report = self.env.ref(
            "merrikh_membership.action_report_membership_card",
            raise_if_not_found=False
        )
        if not report:
            return

        pdf_content, _ = self.env["ir.actions.report"]._render_qweb_pdf(
            report.report_name,
            res_ids=[self.id]
        )

        attachment = self.env["ir.attachment"].sudo().create({
            "name": f"Membership_{self.sequence}.pdf",
            "type": "binary",
            "datas": base64.b64encode(pdf_content),
            "res_model": "merrikh.membership",
            "res_id": self.id,
            "mimetype": "application/pdf",
        })

        template = self.env.ref(
            "merrikh_membership.email_membership_card",
            raise_if_not_found=False
        )
        if template:
            template.sudo().send_mail(
                self.id,
                email_values={"attachment_ids": [(6, 0, [attachment.id])]},
                force_send=True,
            )

    # =========================
    # EXTEND MEMBERSHIP
    # =========================
    def _extend_membership_period(self):
        self.ensure_one()

        if not self.end_date:
            return

        if self.membership_type == "monthly":
            self.end_date += relativedelta(months=1)
        elif self.membership_type == "semiannual":
            self.end_date += relativedelta(months=6)
        elif self.membership_type == "annual":
            self.end_date += relativedelta(years=1)

    # =========================
    # CREATE RECURRING INVOICE
    # =========================
    def _create_recurring_invoice(self):
        self.ensure_one()

        if self.state != "active":
            return

        if self.invoice_id and self.invoice_id.payment_state not in ("paid", "in_payment"):
            return

        self.action_create_invoice()

    # =========================
    # CRON
    # =========================
    @api.model
    def cron_membership_recurring_invoices(self):
        today = date.today()

        memberships = self.search([
            ("state", "=", "active"),
            ("end_date", "<=", today),
        ])

        for rec in memberships:
            rec._create_recurring_invoice()
            rec._extend_membership_period()

    # =========================
    # TERMS
    # =========================
    def _default_terms_text(self):
        return _(
            "أقر بأن جميع البيانات المقدمة صحيحة، وأوافق على شروط "
            "وأحكام رابطة مشجعي نادي المريخ."
        )
