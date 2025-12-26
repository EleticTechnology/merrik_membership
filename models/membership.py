from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date, timedelta
import uuid


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

    membership_type = fields.Selection(
        [
            ("annual", "Annual"),
            ("supporter", "Supporter"),
            ("honorary", "Honorary"),
        ],
        default="annual",
        required=True,
        tracking=True,
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

    invoice_id = fields.Many2one("account.move", copy=False)
    verify_uuid = fields.Char(readonly=True, index=True)

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
    # PORTAL USER (FIXED)
    # =========================
    def _ensure_portal_user(self):
        self.ensure_one()

        if not self.partner_id or not self.partner_id.email:
            raise UserError(_("Email is required for portal access."))

        Users = self.env["res.users"].sudo()
        portal_group = self.env.ref("base.group_portal")

        user = Users.search(
            [("partner_id", "=", self.partner_id.id)],
            limit=1,
        )

        if not user:
            user = Users.create({
                "name": self.partner_id.name,
                "login": self.partner_id.email,
                "email": self.partner_id.email,
                "partner_id": self.partner_id.id,
                "groups_id": [(6, 0, [portal_group.id])],
                "active": True,
            })

        # إرسال دعوة بورتال صحيحة (Signup)
        user.with_context(
            signup_force_type_in_url="signup"
        ).action_reset_password()

        return user

    # =========================
    # ACTIONS
    # =========================
    def action_approve(self):
        for rec in self:
            if rec.state != "draft":
                continue

            rec.state = "approved"

            # إنشاء مستخدم بورتال + دعوة
            rec._ensure_portal_user()

            # إرسال إيميل الموافقة
            template = self.env.ref(
                "merrikh_membership.email_membership_approved",
                raise_if_not_found=False,
            )
            if template:
                template.sudo().send_mail(rec.id, force_send=True)

            if rec.membership_type == "honorary":
                rec._activate_membership()
            else:
                rec.action_create_invoice()

    def action_reject(self):
        for rec in self:
            if rec.state in ("paid", "active"):
                raise UserError(_("You cannot reject a paid or active membership."))
            rec.state = "rejected"

    def action_create_invoice(self):
        for rec in self:
            if rec.state != "approved":
                continue

            product_map = {
                "annual": "merrikh_membership.product_merrikh_membership_annual",
                "supporter": "merrikh_membership.product_merrikh_membership_supporter",
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
                        "price_unit": product.list_price,
                    })
                ],
                "invoice_origin": rec.sequence,
            })

            invoice.action_post()
            rec.invoice_id = invoice.id
            rec.state = "invoiced"

    def action_check_payment_and_activate(self):
        for rec in self:
            if rec.invoice_id and rec.invoice_id.payment_state in ("paid", "in_payment"):
                rec.state = "paid"
                rec._activate_membership()

    # =========================
    # ACTIVATE + SEND CARD
    # =========================
    def _activate_membership(self):
        self.ensure_one()

        if not self.start_date:
            self.start_date = date.today()

        if not self.end_date:
            self.end_date = self.start_date + timedelta(days=365)

        self.state = "active"

        # إرسال بطاقة العضوية PDF
        template = self.env.ref(
            "merrikh_membership.email_membership_card",
            raise_if_not_found=False,
        )
        if template:
            template.sudo().send_mail(self.id, force_send=True)

    # =========================
    # TERMS
    # =========================
    def _default_terms_text(self):
        return _(
            "By submitting this application, I confirm that all provided "
            "information is correct and I agree to the association terms "
            "and membership policy."
        )
