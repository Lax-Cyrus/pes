# -*- coding: utf-8 -*-
{
    "name": "PesaPal API 3.0 Payment Acquirer - MPESA/Airtel-M/EQUITY/Coop/MasterCard/VISA/American-Express",
    "license": "OPL-1",
    "support": "support@optima.co.ke",
    "summary": """
        Accept Card & Mobile Money on Odoo using M-PESA/Airtel-Money/EQUITY BanK/Coop Bank/MasterCard/VISA/American-Expres/e-wallet""",
    "description": """
    """,
    "author": "Optima ICT Services LTD",
    "website": "https://www.optima.co.ke",
    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/master/odoo/addons/base/module/module_data.xml
    # for the full list
    "category": "Accounting",
    "version": "1.0",
    # any module necessary for this one to work correctly
    "depends": ["payment", "account"],
    "price": 329,
    "currency": "EUR",
    "images": ["static/description/cover.png"],
    # always loaded
    "data": [
        # 'security/ir.model.access.csv',
        "views/payment_views.xml",
        "views/payment_pesapal_templates.xml",
        "data/pesapal_provider_data.xml",
    ],
    # only loaded in demonstration mode
    "demo": [
        # 'demo/demo.xml',
    ],
    "application": True,
}
