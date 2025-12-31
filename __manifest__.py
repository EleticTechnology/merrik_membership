{
    "name": "Merrikh Membership Management",
    "version": "17.0.2.0.0",
    "category": "Membership",
    "summary": "Membership subscriptions for Al-Merrikh Fans Association Dubai & Northern Emirates",
    "author": "Eletic Technology",
    "website": "https://eletic-tec.com",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "website",
        "portal",
        "account",
        "payment",          # لعرض زر الدفع/مزودات الدفع (Stripe)
        "website_payment",  # صفحات الدفع على الويب
    ],
    "data": [
        "security/security.xml",
        "security/record_rules.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/product.xml",
        "views/membership_menus_views.xml",
        "views/membership_website_templates.xml",
        "views/membership_portal_templates.xml",
        "views/membership_portal_detail.xml",
        "report/membership_card.xml",
        "data/mail_templates.xml",

    ],
    "application": True,
    "installable": True,
}
