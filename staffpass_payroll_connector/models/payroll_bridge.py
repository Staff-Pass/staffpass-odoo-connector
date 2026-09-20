import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from odoo import _, api, models
from odoo.exceptions import AccessError, ValidationError

MAX_LINES = 2000
MAX_DESCRIPTION = 256
CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$")
JOURNAL_TYPES = {"ACCRUAL", "PAYMENT", "REVERSAL"}
SIDES = {"DEBIT", "CREDIT"}


def _required_text(value, field_name, maximum=256):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(_("%s must be a non-empty string.") % field_name)
    value = value.strip()
    if len(value) > maximum:
        raise ValidationError(_("%s exceeds the maximum length.") % field_name)
    return value


def _money(value, field_name):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(_("%s must be a valid amount.") % field_name) from exc
    if not amount.is_finite() or amount < 0:
        raise ValidationError(_("%s must be finite and non-negative.") % field_name)
    return amount.quantize(Decimal("0.01"))


def _payload_hash(payload):
    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(_("The journal payload must contain JSON values only.")) from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class StaffPassPayrollBridge(models.AbstractModel):
    _name = "staffpass.payroll.bridge"
    _description = "StaffPass Payroll Integration Service"

    @api.model
    def get_catalog(self, company_id):
        company = self._company(company_id)
        account_model = self.env["account.account"].with_company(company)
        accounts = account_model.search(
            [("company_ids", "in", company.id), ("deprecated", "=", False)],
            order="code, id",
            limit=5000,
        )
        journals = (
            self.env["account.journal"]
            .with_company(company)
            .search(
                [("company_id", "=", company.id), ("type", "=", "general")],
                order="code, id",
                limit=500,
            )
        )
        return {
            "contractVersion": "1.0.0",
            "company": {"id": company.staffpass_external_id, "name": company.name},
            "currency": company.currency_id.name,
            "accounts": [
                {"id": account.id, "code": account.code, "name": account.name}
                for account in accounts
            ],
            "journals": [
                {"id": journal.id, "code": journal.code, "name": journal.name}
                for journal in journals
            ],
        }

    @api.model
    def import_journal(self, payload):
        normalized = self._validate_payload(payload)
        company = normalized["company"]
        external_id = normalized["external_id"]
        payload_digest = _payload_hash(payload)

        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [f"staffpass:{company.id}:{external_id}"],
        )
        existing = (
            self.env["staffpass.payroll.import"]
            .sudo()
            .search(
                [("company_id", "=", company.id), ("external_id", "=", external_id)],
                limit=1,
            )
        )
        if existing:
            if existing.payload_hash != payload_digest:
                raise ValidationError(
                    _("The external journal ID already exists with different content.")
                )
            return self._result(existing, duplicate=True)

        account_ids = self._resolve_accounts(company, normalized["account_codes"])
        analytic_ids = self._resolve_analytics(company, normalized["cost_center_codes"])
        line_commands = []
        for line in normalized["lines"]:
            values = {
                "name": line["description"],
                "account_id": account_ids[line["account_code"]].id,
                "debit": float(line["amount"]) if line["side"] == "DEBIT" else 0.0,
                "credit": float(line["amount"]) if line["side"] == "CREDIT" else 0.0,
            }
            if line["cost_center_code"]:
                values["analytic_distribution"] = {
                    str(analytic_ids[line["cost_center_code"]].id): 100.0
                }
            line_commands.append((0, 0, values))

        move = (
            self.env["account.move"]
            .with_company(company)
            .create(
                {
                    "move_type": "entry",
                    "state": "draft",
                    "company_id": company.id,
                    "journal_id": company.staffpass_journal_id.id,
                    "date": normalized["entry_date"],
                    "ref": normalized["reference"],
                    "line_ids": line_commands,
                }
            )
        )
        imported = (
            self.env["staffpass.payroll.import"]
            .sudo()
            .create(
                {
                    "external_id": external_id,
                    "company_id": company.id,
                    "move_id": move.id,
                    "journal_type": normalized["journal_type"],
                    "source_hash": normalized["source_hash"],
                    "payload_hash": payload_digest,
                    "total_debit": float(normalized["total_debit"]),
                    "total_credit": float(normalized["total_credit"]),
                    "currency_id": company.currency_id.id,
                    "line_count": len(normalized["lines"]),
                }
            )
        )
        return self._result(imported, duplicate=False)

    @api.model
    def get_journal_status(self, company_id, external_id):
        company = self._company(company_id)
        imported = (
            self.env["staffpass.payroll.import"]
            .sudo()
            .search(
                [
                    ("company_id", "=", company.id),
                    ("external_id", "=", _required_text(external_id, "external_id", 160)),
                ],
                limit=1,
            )
        )
        if not imported:
            return {"found": False, "externalId": external_id}
        return {"found": True, **self._result(imported, duplicate=True)}

    @api.model
    def reverse_journal(
        self,
        company_id,
        external_id,
        reversal_external_id,
        reversal_date,
        reason,
    ):
        company = self._company(company_id)
        external_id = _required_text(external_id, "external_id", 160)
        reversal_external_id = _required_text(reversal_external_id, "reversal_external_id", 160)
        reason = _required_text(reason, "reason", 160)
        try:
            reversal_date = date.fromisoformat(reversal_date)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("reversal_date must use YYYY-MM-DD.")) from exc
        digest = _payload_hash(
            {
                "companyId": company_id,
                "externalId": external_id,
                "reversalExternalId": reversal_external_id,
                "reversalDate": reversal_date.isoformat(),
                "reason": reason,
            }
        )
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [f"staffpass:{company.id}:{reversal_external_id}"],
        )
        import_model = self.env["staffpass.payroll.import"].sudo()
        existing = import_model.search(
            [
                ("company_id", "=", company.id),
                ("external_id", "=", reversal_external_id),
            ],
            limit=1,
        )
        if existing:
            if existing.payload_hash != digest:
                raise ValidationError(_("The reversal ID already exists with different content."))
            return self._result(existing, duplicate=True)
        original = import_model.search(
            [("company_id", "=", company.id), ("external_id", "=", external_id)],
            limit=1,
        )
        if not original:
            raise ValidationError(_("The original StaffPass journal was not found."))
        reversal = original.move_id.with_company(company)._reverse_moves(
            default_values_list=[
                {
                    "date": reversal_date,
                    "ref": f"{original.move_id.ref or external_id} / {reason}"[:200],
                }
            ],
            cancel=False,
        )
        imported = import_model.create(
            {
                "external_id": reversal_external_id,
                "company_id": company.id,
                "move_id": reversal.id,
                "journal_type": "REVERSAL",
                "source_hash": original.source_hash,
                "payload_hash": digest,
                "total_debit": original.total_credit,
                "total_credit": original.total_debit,
                "currency_id": company.currency_id.id,
                "line_count": len(reversal.line_ids),
            }
        )
        return self._result(imported, duplicate=False)

    def _company(self, external_id):
        self._require_integration_user()
        external_id = _required_text(external_id, "company_id", 120)
        company = (
            self.env["res.company"]
            .sudo()
            .search(
                [
                    ("id", "in", self.env.companies.ids),
                    ("staffpass_connector_enabled", "=", True),
                    ("staffpass_external_id", "=", external_id),
                ],
                limit=2,
            )
        )
        if len(company) != 1:
            raise AccessError(_("No enabled StaffPass company matches this identifier."))
        company = company.sudo()
        if not company.staffpass_journal_id:
            raise ValidationError(_("The StaffPass payroll journal is not configured."))
        return company

    def _require_integration_user(self):
        if not self.env.user.has_group("staffpass_payroll_connector.group_staffpass_integration"):
            raise AccessError(_("The user is not allowed to import StaffPass journals."))

    def _validate_payload(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError(_("The journal payload must be an object."))
        if payload.get("contractVersion") != "1.0.0":
            raise ValidationError(_("Unsupported StaffPass accounting contract version."))
        company = self._company(payload.get("companyId"))
        if payload.get("currency") != company.currency_id.name:
            raise ValidationError(_("The journal currency must match the Odoo company currency."))
        journal_type = payload.get("journalType")
        if journal_type not in JOURNAL_TYPES:
            raise ValidationError(_("Unsupported journal type."))
        try:
            entry_date = date.fromisoformat(payload.get("entryDate", ""))
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("entryDate must use YYYY-MM-DD.")) from exc
        lines = payload.get("lines")
        if not isinstance(lines, list) or not lines or len(lines) > MAX_LINES:
            raise ValidationError(_("The journal must contain between 1 and %s lines.") % MAX_LINES)

        normalized_lines = []
        debit = Decimal("0.00")
        credit = Decimal("0.00")
        account_codes = set()
        cost_center_codes = set()
        for position, line in enumerate(lines):
            if not isinstance(line, dict):
                raise ValidationError(_("Every journal line must be an object."))
            side = line.get("side")
            if side not in SIDES:
                raise ValidationError(_("Line %s has an invalid side.") % position)
            account_code = _required_text(line.get("accountCode"), "accountCode", 120)
            if not CODE_PATTERN.fullmatch(account_code):
                raise ValidationError(_("Line %s has an invalid account code.") % position)
            amount = _money(line.get("amount"), f"lines[{position}].amount")
            if amount == 0:
                raise ValidationError(_("Journal lines cannot have a zero amount."))
            if line.get("currency") != company.currency_id.name:
                raise ValidationError(_("Every line currency must match the company currency."))
            cost_center = line.get("costCenterCode")
            if cost_center is not None:
                cost_center = _required_text(cost_center, "costCenterCode", 120)
                if not CODE_PATTERN.fullmatch(cost_center):
                    raise ValidationError(_("Line %s has an invalid cost center code.") % position)
                cost_center_codes.add(cost_center)
            normalized_lines.append(
                {
                    "side": side,
                    "account_code": account_code,
                    "cost_center_code": cost_center,
                    "amount": amount,
                    "description": _required_text(
                        line.get("description"), "description", MAX_DESCRIPTION
                    ),
                }
            )
            account_codes.add(account_code)
            if side == "DEBIT":
                debit += amount
            else:
                credit += amount

        expected_debit = _money(payload.get("totalDebit"), "totalDebit")
        expected_credit = _money(payload.get("totalCredit"), "totalCredit")
        if debit != credit or debit != expected_debit or credit != expected_credit:
            raise ValidationError(
                _("The journal totals are not balanced or do not match its lines.")
            )
        if payload.get("balanced") is not True:
            raise ValidationError(_("The journal must explicitly declare balanced=true."))

        return {
            "company": company,
            "external_id": (
                f"{_required_text(payload.get('exportJobId'), 'exportJobId', 120)}:{journal_type}"
            ),
            "journal_type": journal_type,
            "entry_date": entry_date,
            "reference": _required_text(payload.get("reference"), "reference", 200),
            "source_hash": _required_text(payload.get("sourceHash"), "sourceHash", 128),
            "lines": normalized_lines,
            "account_codes": account_codes,
            "cost_center_codes": cost_center_codes,
            "total_debit": debit,
            "total_credit": credit,
        }

    def _resolve_accounts(self, company, codes):
        account_model = self.env["account.account"].with_company(company)
        result = {}
        for code in codes:
            matches = account_model.search(
                [
                    ("company_ids", "in", company.id),
                    ("code", "=", code),
                    ("deprecated", "=", False),
                ],
                limit=2,
            )
            if len(matches) != 1:
                raise ValidationError(
                    _("Account code %s must resolve to one active account.") % code
                )
            result[code] = matches
        return result

    def _resolve_analytics(self, company, codes):
        analytic_model = self.env["account.analytic.account"].with_company(company)
        result = {}
        for code in codes:
            matches = analytic_model.search(
                [
                    ("company_id", "in", [False, company.id]),
                    ("code", "=", code),
                    ("active", "=", True),
                ],
                limit=2,
            )
            if len(matches) != 1:
                raise ValidationError(
                    _("Cost center code %s must resolve to one active analytic account.") % code
                )
            result[code] = matches
        return result

    @staticmethod
    def _result(imported, duplicate):
        return {
            "externalId": imported.external_id,
            "moveId": imported.move_id.id,
            "moveName": imported.move_id.name,
            "state": imported.move_id.state,
            "duplicate": duplicate,
            "lineCount": imported.line_count,
        }
