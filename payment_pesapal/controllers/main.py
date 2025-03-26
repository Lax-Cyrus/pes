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

    _pesapal_ipn_url = "/payment/pesapal/ipn"
    _pesapal_callback_url = "/payment/pesapal"

    @http.route(
        _pesapal_callback_url,
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def pesapal_callback(self, **params):
        """Handle callback data sent by PesaPal."""
        LOGGER.info("PESAPAL: Processing callback with data: %s", params)

        tx = request.env["payment.transaction"].sudo().search([
            ("reference", "=", params.get("OrderMerchantReference")),
            ("provider_code", "=", "pesapal"),
        ], limit=1)

        if not tx:
            LOGGER.error("PESAPAL: No transaction found matching reference %s", params.get("OrderMerchantReference"))
            return request.redirect("/payment/status?error=Transaction Not Found")

        # Attach tracking ID if missing
        if not tx.pesapal_tracking_id:
            tx.pesapal_tracking_id = params.get("OrderTrackingId")

        # If still pending, fetch the latest status
        if tx.state == "pending":
            LOGGER.info("PESAPAL: Transaction pending. Checking status for reference %s", tx.reference)
            res = tx.provider_id.pesapal_get_txn_status(params)
            if res:
                tx._handle_feedback_data("pesapal", res)

        return request.redirect("/payment/status")

    @http.route(
        _pesapal_ipn_url,
        type="http",
        auth="public",
        methods=["GET", "POST"],
    )
    def pesapal_ipn(self, **data):
        """Receive and process IPN data from PesaPal."""
        LOGGER.info("PESAPAL: Processing IPN with data: %s", data)

        tx = request.env["payment.transaction"].sudo().search([
            ("reference", "=", data.get("OrderMerchantReference")),
            ("provider_code", "=", "pesapal"),
        ], limit=1)

        if not tx:
            LOGGER.warning("PESAPAL: No transaction found for IPN reference %s", data.get("OrderMerchantReference"))
            return Response("Transaction Not Found", status=200)  # Avoid breaking the IPN response flow

        if tx.pesapal_tracking_id != data.get("OrderTrackingId"):
            LOGGER.warning("PESAPAL: IPN received with mismatched tracking ID")
            return Response("Tracking ID Mismatch", status=200)

        if tx.state not in ["pending", "authorized"]:  # Avoid processing completed transactions again
            LOGGER.info("PESAPAL: Ignoring IPN for already processed transaction %s", tx.reference)
            return Response("OK", status=200)

        res = tx.provider_id.pesapal_get_txn_status(data)
        if res:
            tx._handle_feedback_data("pesapal", res)
            return Response("OK", status=200)

        LOGGER.error("PESAPAL: Failed to retrieve transaction status for reference %s", tx.reference)
        return Response("Failed", status=500)
