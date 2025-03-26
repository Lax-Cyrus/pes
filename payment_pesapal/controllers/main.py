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
        LOGGER.info("Beginning PesaPal Callback processing with data: %s", params)

        tx = (
            request.env["payment.transaction"]
            .sudo()
            ._get_tx_from_feedback_data("pesapal", params)
        )

        if tx:
            if not tx.pesapal_tracking_id:
                tx.pesapal_tracking_id = params.get("OrderTrackingId")
            if tx.state == "pending":
                LOGGER.info("PESAPAL: Transaction is pending (IPN not received yet) fetching transaction data")
                res = tx.provider_id.pesapal_get_txn_status(params)
                if res:
                    tx._handle_feedback_data("pesapal", res)
        else:
            raise ValidationError(_("PESAPAL: Unable to retrieve payment transaction matching the pesapal details received."))
        
        return request.redirect("/payment/status")

    @http.route(
        _pesapal_ipn_url,
        type="http",
        auth="public",
        methods=["GET", "POST"],
    )
    def pesapal_ipn(self, **data):
        """Receive and process IPN data from PesaPal."""
        LOGGER.info("Beginning PesaPal IPN processing with data: %s", data)

        # Check for existing transaction to avoid duplicates
        tx = request.env["payment.transaction"].sudo().search([
            ("reference", "=", data.get("OrderMerchantReference")),
            ("pesapal_tracking_id", "=", data.get("OrderTrackingId")),
        ], limit=1)

        if tx:
            # Transaction already exists, update status
            res = tx.provider_id.pesapal_get_txn_status(data)
            if res:
                tx._handle_feedback_data("pesapal", res)
            else:
                LOGGER.info("PESAPAL: %s", res)
                raise ValidationError(_("PESAPAL: Cannot get transaction status"))
        else:
            # No matching transaction found; log and skip
            LOGGER.warning(_("PESAPAL: No transaction matching the IPN data received"))
            return Response("OK", status=200)  # receive receipt of IPN

        return Response("OK", status=200)
