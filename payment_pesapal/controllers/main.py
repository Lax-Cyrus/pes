# -*- coding: utf-8 -*-
"""
Odoo Proprietary License v1.0.
see License:
https://www.odoo.com/documentation/user/14.0/legal/licenses/licenses.html#odoo-apps
# Copyright ©2022 Bernard K. Too<bernard.too@optima.co.ke>
"""
import logging
from odoo import _, http
from odoo.exceptions import ValidationError
from odoo.http import Response, request

LOGGER = logging.getLogger(__name__)

class PesaPalController(http.Controller):
    """Controller for handling PesaPal payment callbacks and IPN messages."""
    _pesapal_callback_url = "/payment/pesapal"
    _pesapal_ipn_url = "/payment/pesapal/ipn"

    @http.route(
        _pesapal_callback_url,
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def pesapal_callback(self, **params):
        """Handle callback data sent by PesaPal."""
        LOGGER.info("Beginning PesaPal Callback processing with data: %s", params)
        
        # Find existing transaction or create a new one
        tx = request.env["payment.transaction"].sudo().search([
            ("reference", "=", params.get("OrderMerchantReference")),
        ], limit=1)

        if not tx:
            LOGGER.warning("No existing transaction found. Creating a new transaction.")
            # Create a new transaction if not exists
            try:
                tx = request.env["payment.transaction"].sudo().create({
                    'reference': params.get("OrderMerchantReference"),
                    'provider_code': 'pesapal',
                    'pesapal_tracking_id': params.get("OrderTrackingId"),
                    'state': 'pending'
                })
            except Exception as e:
                LOGGER.error(f"Error creating transaction: {e}")
                raise ValidationError(_("PESAPAL: Unable to create transaction"))

        # Update tracking ID if not set
        if not tx.pesapal_tracking_id:
            tx.pesapal_tracking_id = params.get("OrderTrackingId")

        # Fetch and handle transaction status
        if tx.state == "pending":
            LOGGER.info("PESAPAL: Transaction is pending, fetching transaction data")
            try:
                res = tx.provider_id.pesapal_get_txn_status(params)
                if res:
                    tx._handle_feedback_data("pesapal", res)
                else:
                    LOGGER.warning("Unable to retrieve transaction status")
            except Exception as e:
                LOGGER.error(f"Error processing transaction status: {e}")
                raise ValidationError(_("PESAPAL: Unable to retrieve payment transaction status"))

        return request.redirect("/payment/status")

    @http.route(
        _pesapal_ipn_url,
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def pesapal_ipn(self, **data):
        """Receive and process IPN data from PesaPal."""
        LOGGER.info("Beginning PesaPal IPN processing with data: %s", data)

        # Find transaction by merchant reference
        tx = request.env["payment.transaction"].sudo().search([
            ("reference", "=", data.get("OrderMerchantReference")),
        ], limit=1)

        if tx:
            # Update tracking ID if not set
            if not tx.pesapal_tracking_id:
                tx.pesapal_tracking_id = data.get("OrderTrackingId")

            # Fetch and update transaction status
            try:
                res = tx.provider_id.pesapal_get_txn_status(data)
                if res:
                    tx._handle_feedback_data("pesapal", res)
                else:
                    LOGGER.warning("Unable to retrieve transaction status")
            except Exception as e:
                LOGGER.error(f"Error processing IPN: {e}")
                raise ValidationError(_("PESAPAL: Cannot get transaction status"))
        else:
            # Log warning for unmatched transaction
            LOGGER.warning(_("PESAPAL: No transaction matching the IPN data received"))

        return Response("OK", status=200)