from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal
import base64


# =========================================================
# WEBSITE (PUBLIC REGISTRATION)
# =========================================================
class MerrikhMembershipWebsite(http.Controller):

    @http.route("/membership", type="http", auth="public", website=True)
    def membership_form(self, **kw):
        return request.render("merrikh_membership.website_membership_form", {})

    @http.route(
        "/membership/submit",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def membership_submit(self, **post):

        if not post.get("accept_terms"):
            return request.render(
                "merrikh_membership.website_membership_form",
                {
                    "error": _("يجب الموافقة على الشروط"),
                    "post": post,
                },
            )

        # Partner
        user = request.env.user
        if user and not user._is_public():
            partner = user.partner_id
        else:
            partner = request.env["res.partner"].sudo().create({
                "name": post.get("name"),
                "phone": post.get("phone"),
                "email": post.get("email"),
            })

        files = request.httprequest.files

        vals = {
            "name": post.get("name"),
            "phone": post.get("phone"),
            "email": post.get("email"),
            "nationality": post.get("nationality"),
            "id_number": post.get("id_number"),
            "membership_type": post.get("membership_type") or "annual",
            "accept_terms": True,
            "partner_id": partner.id,
        }

        if files.get("image"):
            vals["image"] = base64.b64encode(files["image"].read())
        if files.get("id_image"):
            vals["id_image"] = base64.b64encode(files["id_image"].read())

        membership = request.env["merrikh.membership"].sudo().create(vals)

        return request.render(
            "merrikh_membership.website_membership_thanks",
            {"membership": membership},
        )


# =========================================================
# PORTAL
# =========================================================
class MerrikhPortal(CustomerPortal):

    # -----------------------------------------------------
    # Portal Home Counter
    # -----------------------------------------------------
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)

        if "membership" in counters:
            values["membership_count"] = request.env[
                "merrikh.membership"
            ].sudo().search_count([
                ("partner_id", "=", request.env.user.partner_id.id)
            ])

        return values

    # -----------------------------------------------------
    # List My Memberships
    # -----------------------------------------------------
    @http.route("/my/memberships", type="http", auth="user", website=True)
    def portal_my_memberships(self, **kw):
        memberships = request.env["merrikh.membership"].sudo().search([
            ("partner_id", "=", request.env.user.partner_id.id)
        ])

        return request.render(
            "merrikh_membership.portal_my_memberships",
            {"memberships": memberships},
        )

    # -----------------------------------------------------
    # Membership Details
    # -----------------------------------------------------
    @http.route(
        "/my/memberships/<int:membership_id>",
        type="http",
        auth="user",
        website=True,
    )
    def portal_membership_detail(self, membership_id, **kw):
        membership = request.env["merrikh.membership"].sudo().browse(membership_id)

        if not membership.exists() or membership.partner_id != request.env.user.partner_id:
            return request.not_found()

        return request.render(
            "merrikh_membership.portal_membership_detail",
            {"membership": membership},
        )

    # -----------------------------------------------------
    # DOWNLOAD MEMBERSHIP CARD (PDF)
    # -----------------------------------------------------
    @http.route(
        "/my/memberships/<int:membership_id>/card",
        type="http",
        auth="user",
        website=True,
    )
    def portal_membership_card(self, membership_id):
        membership = request.env["merrikh.membership"].sudo().browse(membership_id)

        if not membership.exists() or membership.partner_id != request.env.user.partner_id:
            return request.not_found()

        pdf, _ = request.env.ref(
            "merrikh_membership.action_report_membership_card"
        )._render_qweb_pdf([membership.id])

        headers = [
            ("Content-Type", "application/pdf"),
            (
                "Content-Disposition",
                f'inline; filename=Membership_{membership.sequence}.pdf',
            ),
        ]
        return request.make_response(pdf, headers=headers)

    # -----------------------------------------------------
    # CREATE INVOICE FROM PORTAL
    # -----------------------------------------------------
    @http.route(
        "/my/memberships/<int:membership_id>/create_invoice",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def portal_create_invoice(self, membership_id, **kw):
        membership = request.env["merrikh.membership"].sudo().browse(membership_id)

        if not membership.exists() or membership.partner_id != request.env.user.partner_id:
            return request.not_found()

        if membership.state == "approved":
            membership.action_create_invoice()

        return request.redirect(f"/my/memberships/{membership.id}")

    # -----------------------------------------------------
    # CHECK PAYMENT & ACTIVATE
    # -----------------------------------------------------
    @http.route(
        "/my/memberships/<int:membership_id>/check_payment",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
        csrf=True,
    )
    def portal_check_payment(self, membership_id, **kw):
        membership = request.env["merrikh.membership"].sudo().browse(membership_id)

        if not membership.exists() or membership.partner_id != request.env.user.partner_id:
            return request.not_found()

        membership.action_check_payment_and_activate()

        return request.redirect(f"/my/memberships/{membership.id}")
