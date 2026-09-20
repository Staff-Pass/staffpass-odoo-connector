from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    staffpass_connector_enabled = fields.Boolean(
        string="Enable StaffPass payroll imports",
        default=False,
        groups="base.group_system",
    )
    staffpass_external_id = fields.Char(
        string="StaffPass company ID",
        copy=False,
        index=True,
        groups="base.group_system",
    )
    staffpass_journal_id = fields.Many2one(
        "account.journal",
        string="StaffPass payroll journal",
        check_company=True,
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
        groups="base.group_system",
    )

    @api.constrains(
        "staffpass_connector_enabled",
        "staffpass_external_id",
        "staffpass_journal_id",
    )
    def _check_staffpass_configuration(self):
        for company in self:
            external_id = (company.staffpass_external_id or "").strip()
            if company.staffpass_connector_enabled:
                if not external_id:
                    raise ValidationError(_("A StaffPass company ID is required."))
                if not company.staffpass_journal_id:
                    raise ValidationError(_("A general journal is required for StaffPass imports."))
            if external_id:
                duplicate = self.search_count(
                    [
                        ("id", "!=", company.id),
                        ("staffpass_external_id", "=", external_id),
                    ]
                )
                if duplicate:
                    raise ValidationError(_("The StaffPass company ID must be unique."))
