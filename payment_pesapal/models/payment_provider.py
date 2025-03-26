# -*- coding: utf-8 -*-
"""
Odoo Proprietary License v1.0.

see License:
https://www.odoo.com/documentation/user/15.0/legal/licenses/licenses.html#odoo-apps
# Copyright ©2022 Bernard K. Too<bernard.too@optima.co.ke>
"""
import logging
import requests

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError

LOGGER = logging.getLogger(__name__)

class AcquirerPesaPal(models.Model):
    """Add Pesapal objects and methods."""

    _inherit = "payment.provider"

    # [Existing fields from your original code remain the same]

    def _pesapal_get_access_token(self):
        self.ensure_one()
        payload = None
        if (
            not self.pesapal_access_token
            or fields.Datetime.now() >= self.pesapal_token_expiry_date
        ):
            body = {
                "consumer_key": self.pesapal_consumer_key,
                "consumer_secret": self.pesapal_consumer_secret,
            }
            try:
                res = requests.post(
                    self.pesapal_auth_url,
                    json=body,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            except requests.exceptions.RequestException as exc:
                LOGGER.warning("PESAPAL: %s", exc)
            else:
                if res.status_code == 200:
                    payload = res.json()
                    LOGGER.info(
                        "PESAPAL: Response Code: %s",
                        res.status_code,
                    )
                else:
                    msg = _("Cannot fetch access token. Received HTTP Error code ")
                    LOGGER.warning(
                        "PESAPAL: "
                        + msg
                        + str(res.status_code)
                        + ", "
                        + res.reason
                        + ". URL: "
                        + res.url
                    )
                    LOGGER.info("PESAPAL:%s", res.json())
            if payload:
                if not payload.get("error"):
                    self.write(
                        dict(
                            pesapal_access_token=payload.get("token"),
                            pesapal_token_expiry_date=payload.get("expiryDate")
                            .split(".")[0]
                            .replace("T", " "),
                        ),
                    )
                else:
                    LOGGER.warning("%s", payload.get("error"))
                    raise UserError(payload.get("error"))

        return self.pesapal_access_token

    def pesapal_submit_order(self, data):
        """Submit order."""
        self.ensure_one()
        amount = data.get("amount")
        if (
            int(data.get("currency_id")) != self.pesapal_currency_id.id
        ):  # multi-currency support
            amount = (
                self.env["res.currency"]
                .browse([int(data.get("currency_id"))])
                ._convert(
                    from_amount=float(amount),
                    company=self.company_id,
                    to_currency=self.pesapal_currency_id,
                    date=fields.Date.today(),
                )
            )
        body = {
            "id": data.get("reference"),
            "currency": self.pesapal_currency_id.name,
            "description": data.get("reference"),
            "Amount": float(amount),
            "callback_url": self.pesapal_callback_url,
            "notification_id": self.pesapal_ipn_id,
            "billing_address": data.get("billing_address"),
        }
        try:
            res = requests.post(
                self.pesapal_order_url,
                json=body,
                headers={
                    "Authorization": "Bearer %s" % self._pesapal_get_access_token(),
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        except requests.exceptions.RequestException as exc:
            LOGGER.warning("PESAPAL: %s", exc)
            return False
        else:
            if res.status_code == 200:
                jsn = res.json()
                LOGGER.info(
                    "PESAPAL: Response Code: %s. \
                            <amount requested: %s %s> <Order ref: %s>",
                    jsn.get("status", ""),
                    amount,
                    self.pesapal_currency_id.name,
                    data.get("reference"),
                )
                txn = self.env["payment.transaction"].search(
                    [
                        ("reference", "=", jsn.get("merchant_reference")),
                        ("provider_code", "=", "pesapal"),
                    ],
                    limit=1,
                )
                if txn:
                    txn.write(
                        {
                            "last_state_change": fields.Datetime.now(),
                            "pesapal_tracking_id": jsn.get("order_tracking_id"),
                            "state": "pending",
                        }
                    )
                return jsn
            else:
                msg = _(
                    "Cannot submit request for the order. Received HTTP Error code "
                )
                LOGGER.warning(
                    "PESAPAL: "
                    + msg
                    + str(res.status_code)
                    + ", "
                    + res.reason
                    + ". URL: "
                    + res.url
                )
                LOGGER.info("PESAPAL:%s", res.json())
        return False

    def pesapal_get_txn_status(self, data):
        """Get Pesapal transaction status after receving IPN."""
        self.ensure_one()
        tracking_id = data.get("OrderTrackingId")
        body = {
            "orderTrackingId": tracking_id,
        }
        url = self.pesapal_txn_status_url + "=%s" % tracking_id
        try:
            res = requests.get(
                url,
                json=body,
                headers={
                    "Authorization": "Bearer %s" % self._pesapal_get_access_token(),
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        except requests.exceptions.RequestException as exc:
            LOGGER.warning("PESAPAL: %s", exc)
            return False
        else:
            if res.status_code == 200:
                payload = res.json()
                LOGGER.info(
                    "PESAPAL: Response Code: %s, Pesapal transaction status received.",
                    res.status_code,
                )
                return payload
            else:
                msg = _(
                    "PESAPAL: Cannot fetch pesapal trasnsaction status. Received HTTP Error code "
                )
                msg += "%s, %s. URL:%s" % (str(res.status_code), res.reason, res.url)
                LOGGER.info("PESAPAL:%s", res.json())
                raise UserError(msg)
        return False

class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    pesapal_payment_method = fields.Char('Payment Method')
    pesapal_payment_account = fields.Char('Payment Account')
    pesapal_tracking_id = fields.Char('Pesapal Tracking ID')

    def _handle_feedback_data(self, provider_code, data):
        """
        Override to automatically create invoice and validate payment
        """
        # Call parent method first to ensure standard processing
        res = super()._handle_feedback_data(provider_code, data)
        
        # Check if this is a Pesapal transaction and payment is successful
        if provider_code == 'pesapal':
            # Determine payment status from Pesapal response
            status = data.get('status', '').lower()
            
            # Map Pesapal statuses to Odoo actions
            successful_statuses = ['completed', 'success', 'paid']
            
            if status in successful_statuses:
                # Try to create invoice if not already created
                self._create_invoice_from_transaction()
                
                # Validate the payment
                self._validate_payment()
        
        return res

    def _create_invoice_from_transaction(self):
        """
        Create invoice from the sales order associated with this transaction
        """
        for transaction in self:
            # Find associated sale order
            sale_order = self.env['sale.order'].sudo().search([
                ('name', '=', transaction.reference)
            ], limit=1)
            
            if sale_order:
                try:
                    # Confirm sale order if not confirmed
                    if sale_order.state in ['draft', 'sent']:
                        sale_order.action_confirm()
                    
                    # Create invoice
                    invoices = sale_order._create_invoices()
                    
                    # Validate invoice
                    for invoice in invoices:
                        invoice.action_post()
                    
                    return invoices
                except Exception as e:
                    self.env.cr.rollback()
                    self.env['payment.transaction'].sudo().create({
                        'reference': f"Error-{transaction.reference}",
                        'amount': transaction.amount,
                        'state': 'error',
                        'provider_id': transaction.provider_id.id,
                        'partner_id': transaction.partner_id.id,
                        'payment_id': transaction.payment_id.id,
                    })
                    raise ValidationError(_(f"Could not process invoice: {str(e)}"))
        return False

    def _validate_payment(self):
        """
        Validate the payment for the transaction
        """
        for transaction in self:
            # Find associated payment
            payment = transaction.payment_id
            
            if payment and payment.state != 'posted':
                try:
                    payment.action_post()
                except Exception as e:
                    self.env.cr.rollback()
                    raise ValidationError(_(f"Could not validate payment: {str(e)}"))