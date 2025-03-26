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
from odoo.exceptions import UserError

LOGGER = logging.getLogger(__name__)

class AcquirerPesaPal(models.Model):
    """Add Pesapal objects and methods."""

    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[('pesapal', "Pesapal")],
        ondelete={'pesapal': 'set default'},
        default=lambda self: 'pesapal',
    )
    pesapal_consumer_key = fields.Char(
        "Pesapal Consumer Key",
        required_if_provider="pesapal",
        default="qkio1BGGYAXTu2JOfm7XSXNruoZsrqEW",
    )
    pesapal_consumer_secret = fields.Char(
        "PesaPal Consumer Secret",
        required_if_provider="pesapal",
        default="osGQ364R49cXKeOYSpaOnT++rHs=",
    )
    pesapal_auth_url = fields.Char(
        "Pesapal Access Token URL",
        required_if_provider="pesapal",
        default="https://cybqa.pesapal.com/pesapalv3/api/Auth/RequestToken",
    )
    pesapal_ipn_id = fields.Char(
        "Pesapal Registered IPN ID",
        required_if_provider="pesapal",
    )
    pesapal_order_url = fields.Char(
        "Pesapal Order Request URL",
        required_if_provider="pesapal",
        default="https://cybqa.pesapal.com/pesapalv3/api/Transactions/SubmitOrderRequest",
    )
    pesapal_callback_url = fields.Char(
        "Pesapal Callback URL",
        required_if_provider="pesapal",
        default=lambda self: self.env["ir.config_parameter"].get_param(
            "web.base.url", ""
        )
        + "/payment/pesapal",
    )
    pesapal_txn_status_url = fields.Char(
        "Pesapal Transaction Status URL",
        required_if_provider="pesapal",
        default="https://cybqa.pesapal.com/pesapalv3/api/Transactions/GetTransactionStatus?orderTrackingId",
    )
    pesapal_access_token = fields.Char("Pesapal Access Token", readonly=True)
    pesapal_token_expiry_date = fields.Datetime(
        "Token Expiry Date",
        default=lambda self: fields.Datetime.now(),
        readonly=True,
    )
    pesapal_currency_id = fields.Many2one(
        "res.currency",
        "Pesapal Currency",
        required_if_provider="pesapal",
        default=lambda self: self.env.ref("base.KES").id,
    )

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