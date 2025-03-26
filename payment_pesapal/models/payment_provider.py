import logging
import requests
from odoo import _, api, fields, models

LOGGER = logging.getLogger(__name__)

class PaymentAcquirerPesapal(models.Model):
    _inherit = "payment.provider"

    pesapal_order_url = fields.Char("Pesapal Order URL", required=True)
    pesapal_currency_id = fields.Many2one("res.currency", string="Pesapal Currency")
    pesapal_callback_url = fields.Char("Callback URL", required=True)
    pesapal_ipn_id = fields.Char("IPN Notification ID", required=True)

    def _pesapal_get_access_token(self):
        """Get access token from Pesapal."""
        self.ensure_one()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body = {
            "consumer_key": self.pesapal_consumer_key,
            "consumer_secret": self.pesapal_consumer_secret,
        }
        try:
            res = requests.post(self.pesapal_auth_url, json=body, headers=headers)
            res.raise_for_status()
            token = res.json().get("token", "")
            if not token:
                raise ValueError("Invalid access token response from Pesapal")
            return token
        except requests.exceptions.RequestException as exc:
            LOGGER.error("PESAPAL: Error getting access token: %s", exc)
            raise

    def pesapal_submit_order(self, data):
        """Submit an order to Pesapal."""
        self.ensure_one()
        amount = data.get("amount")
        reference = data.get("reference")

        # Prevent duplicate orders
        existing_txn = self.env["payment.transaction"].search([
            ("reference", "=", reference),
            ("provider_code", "=", "pesapal"),
        ], limit=1)

        if existing_txn:
            LOGGER.warning("PESAPAL: Duplicate order detected for reference %s", reference)
            return existing_txn  # Return existing transaction instead of creating a new one

        # Currency conversion if needed
        # if int(data.get("currency_id")) != self.pesapal_currency_id.id:
            amount = self.env["res.currency"].browse([int(data.get("currency_id"))])._convert(
                from_amount=float(amount),
                company=self.company_id,
                to_currency=self.pesapal_currency_id,
                date=fields.Date.today(),
            )

        body = {
            "id": reference,
            "currency": self.pesapal_currency_id.name,
            "description": reference,
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
            res.raise_for_status()
            jsn = res.json()
            
            LOGGER.info(
                "PESAPAL: Response Code: %s. <amount: %s %s> <Order ref: %s>",
                jsn.get("status", ""),
                amount,
                self.pesapal_currency_id.name,
                reference,
            )

            txn = self.env["payment.transaction"].create({
                "reference": reference,
                "provider_code": "pesapal",
                "last_state_change": fields.Datetime.now(),
                "pesapal_tracking_id": jsn.get("order_tracking_id"),
                "state": "pending",
            })
            return txn

        except requests.exceptions.RequestException as exc:
            LOGGER.error("PESAPAL: Request error - %s", exc)
        except ValueError as ve:
            LOGGER.error("PESAPAL: Data error - %s", ve)

        return False

class PaymentTransactionPesapal(models.Model):
    _inherit = "payment.transaction"

    pesapal_tracking_id = fields.Char("Pesapal Tracking ID")

    def _pesapal_check_status(self):
        """Check the payment status from Pesapal."""
        for transaction in self:
            if transaction.provider_code != "pesapal":
                continue
            
            tracking_id = transaction.pesapal_tracking_id
            if not tracking_id:
                LOGGER.warning("PESAPAL: No tracking ID for transaction %s", transaction.reference)
                continue

            try:
                res = requests.get(
                    f"{transaction.provider_id.pesapal_status_url}/{tracking_id}",
                    headers={
                        "Authorization": "Bearer %s" % transaction.provider_id._pesapal_get_access_token(),
                        "Accept": "application/json",
                    },
                )
                res.raise_for_status()
                response = res.json()
                status = response.get("status")

                if status == "COMPLETED":
                    transaction.write({"state": "done"})
                    LOGGER.info("PESAPAL: Payment completed for reference %s", transaction.reference)
                elif status == "FAILED":
                    transaction.write({"state": "cancel"})
                    LOGGER.info("PESAPAL: Payment failed for reference %s", transaction.reference)
                elif status == "PENDING":
                    transaction.write({"state": "pending"})
                    LOGGER.info("PESAPAL: Payment pending for reference %s", transaction.reference)

            except requests.exceptions.RequestException as exc:
                LOGGER.error("PESAPAL: Error checking status for reference %s - %s", transaction.reference, exc)
