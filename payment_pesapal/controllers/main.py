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
import werkzeug

LOGGER = logging.getLogger(__name__)

class PesaPalController(http.Controller):
    """Controller for handling PesaPal payment callbacks and IPN messages."""
    _pesapal_callback_url = "/payment/pesapal"
    _pesapal_ipn_url = "/payment/pesapal/ipn"
    _pesapal_success_url = "/payment/pesapal/success"
    _pesapal_failure_url = "/payment/pesapal/failure"

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
        
        try:
            # Find existing transaction
            tx = request.env["payment.transaction"].sudo().search([
                ("reference", "=", params.get("OrderMerchantReference")),
            ], limit=1)

            if not tx:
                LOGGER.warning("No existing transaction found. Creating a new transaction.")
                tx = request.env["payment.transaction"].sudo().create({
                    'reference': params.get("OrderMerchantReference"),
                    'provider_code': 'pesapal',
                    'pesapal_tracking_id': params.get("OrderTrackingId"),
                    'state': 'pending'
                })

            # Update tracking ID if not set
            if not tx.pesapal_tracking_id:
                tx.pesapal_tracking_id = params.get("OrderTrackingId")

            # Fetch and handle transaction status
            if tx.state == "pending":
                LOGGER.info("PESAPAL: Transaction is pending, fetching transaction data")
                res = tx.provider_id.pesapal_get_txn_status(params)
                
                if res:
                    # Handle feedback will create invoice
                    tx._handle_feedback_data("pesapal", res)
                    
                    # Determine success based on status
                    status = res.get('status', '').lower()
                    successful_statuses = ['completed', 'success', 'paid']
                    
                    if status in successful_statuses:
                        return werkzeug.utils.redirect(f"{self._pesapal_success_url}?reference={tx.reference}")
                    else:
                        return werkzeug.utils.redirect(f"{self._pesapal_failure_url}?reference={tx.reference}")
                else:
                    return werkzeug.utils.redirect(f"{self._pesapal_failure_url}?reference={tx.reference}")

        except Exception as e:
            LOGGER.error(f"Error in Pesapal callback: {e}")
            return werkzeug.utils.redirect(f"{self._pesapal_failure_url}?error={str(e)}")

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

    @http.route(
        _pesapal_success_url,
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def pesapal_success(self, reference=None, **kwargs):
        """Handle successful payment"""
        if not reference:
            return request.redirect("/")
        
        try:
            tx = request.env["payment.transaction"].sudo().search([
                ("reference", "=", reference)
            ], limit=1)
            
            if tx:
                # Find associated sale order
                sale_order = request.env['sale.order'].sudo().search([
                    ('name', '=', reference)
                ], limit=1)
                
                if sale_order:
                    # Redirect to invoice
                    invoices = sale_order.invoice_ids.filtered(lambda inv: inv.state == 'posted')
                    if invoices:
                        return request.redirect(f"/my/invoice/{invoices[0].id}")
        except Exception as e:
            LOGGER.error(f"Error in success redirect: {e}")
        
        return request.redirect("/my/home")

    @http.route(
        _pesapal_failure_url,
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def pesapal_failure(self, reference=None, error=None, **kwargs):
        """Handle payment failure"""
        return request.render('payment.payment_error', {
            'reference': reference,
            'error': error or 'Payment failed or was cancelled'
        })