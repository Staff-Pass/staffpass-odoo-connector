from odoo import fields, models


class StaffPassPayrollImport(models.Model):
    _name = "staffpass.payroll.import"
    _description = "StaffPass Payroll Journal Import"
    _order = "create_date desc, id desc"
    _check_company_auto = True

    external_id = fields.Char(required=True, readonly=True, index=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        readonly=True,
        index=True,
    )
    move_id = fields.Many2one(
        "account.move",
        required=True,
        readonly=True,
        index=True,
        check_company=True,
        ondelete="restrict",
    )
    journal_type = fields.Selection(
        [("ACCRUAL", "Accrual"), ("PAYMENT", "Payment"), ("REVERSAL", "Reversal")],
        required=True,
        readonly=True,
    )
    source_hash = fields.Char(required=True, readonly=True)
    payload_hash = fields.Char(required=True, readonly=True, groups="base.group_system")
    total_debit = fields.Monetary(required=True, readonly=True)
    total_credit = fields.Monetary(required=True, readonly=True)
    currency_id = fields.Many2one("res.currency", required=True, readonly=True)
    line_count = fields.Integer(required=True, readonly=True)
    move_state = fields.Selection(related="move_id.state", string="Move state")

    _company_external_unique = models.Constraint(
        "unique(company_id, external_id)",
        "This StaffPass journal was already imported for the company.",
    )
