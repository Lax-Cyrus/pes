# -*- coding: utf-8 -*-
"""
Odoo Proprietary License v1.0.

see License:
https://www.odoo.com/documentation/user/14.0/legal/licenses/licenses.html#odoo-apps
# Copyright ©2022 Bernard K. Too<bernard.too@optima.co.ke>
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

LOGGER = logging.getLogger(__name__)


class TransactionPesaPal(models.Model):
    """Process Pesapal transactions."""

    _inherit = "payment.transaction"

    pesapal_payment_method = fields.Char("PesaPal Payment Method")
    pesapal_payment_account = fields.Char("PesaPal Payment Account")
    pesapal_tracking_id = fields.Char("PesaPal Order Track ID")

    def _get_specific_processing_values(self, processing_values):
        """Return a dict of pesapal-specific values used to process the transaction.

        For an acquirer to add its own processing values, it must overwrite this method and return a
        dict of acquirer-specific values based on the generic values returned by this method.
        Acquirer-specific values take precedence over those of the dict of generic processing
        values.

        :param dict processing_values: The generic processing values of the transaction
        :return: The dict of acquirer-specific processing values
        :rtype: dict
        """
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != "pesapal":
            return res
        return dict(
            billing_address=dict(
                email_address=self.partner_email,
                phone_number=self.partner_phone,
                line_1=self.partner_address,
                city=self.partner_city,
                first_name=self.partner_id.display_name,
                zip_code=self.partner_zip,
            )
        )

    def _get_specific_rendering_values(self, processing_values):
        """Override of payment to return Pesapal-specific rendering values.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic and specific processing values of the transaction
        :return: The dict of acquirer-specific processing values
        :rtype: dict
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != "pesapal":
            return res
        vals = self.provider_id.pesapal_submit_order(processing_values)
        return {
            "redirect_url": vals.get("redirect_url"),
            "order_tracking_id": vals.get("order_tracking_id"),
        }

    @api.model
    def _get_tx_from_feedback_data(self, provider_code, data):
        """Find the transaction based on the pesapal feedback data.

        For pesapal to handle transaction post-processing, it must overwrite this method and
        return the transaction matching the data.

        :param str provider: The provider of the acquirer that handled the transaction
        :param dict data: The feedback data sent by pesapal
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        """
        tx = super()._get_tx_from_feedback_data(provider_code, data)
        if provider_code != "pesapal":
            return tx
        if not data:
            raise ValidationError(_("PESAPAL: Missing feedback data"))
        reference = data.get("merchant_reference") or data.get("OrderMerchantReference")
        tx = self.search([("reference", "=", reference), ("provider_code", "=", "pesapal")])
        if not tx:
            raise ValidationError(
                "PESAPAL: "
                + _("No transaction found matching reference %s.", reference)
            )
        return tx

    def _process_feedback_data(self, data):
        """Override of payment to process the transaction based on pesapal data.

        Note: self.ensure_one()

        :param dict data: The txn status feedback data sent by pesapal
        :return: None
        :raise: ValidationError if inconsistent data were received
        """
        super()._process_feedback_data(data)
        if self.provider_code != "pesapal":
            return

        payment_status = data.get("status_code")
        self.acquirer_reference = data.get("confirmation_code")
        self.pesapal_payment_method = data.get("payment_method")
        self.pesapal_payment_account = data.get("payment_account")
        status_message = data.get("payment_status_description") + " %s" % data

        if payment_status == 1:
            self._set_done(state_message=status_message)
        elif payment_status == 2:
            self._set_canceled(state_message=status_message)
        elif payment_status == 3:
            self._set_pending(state_message=status_message)
        else:  # status = 0 or otherwise
            self._set_error(status_message)