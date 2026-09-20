from copy import deepcopy

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStaffPassPayrollBridge(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.expense = (
            cls.env["account.account"]
            .with_company(cls.company)
            .create(
                {
                    "name": "StaffPass Payroll Expense",
                    "code": "SP6100",
                    "account_type": "expense",
                    "company_ids": [Command.set(cls.company.ids)],
                }
            )
        )
        cls.payable = (
            cls.env["account.account"]
            .with_company(cls.company)
            .create(
                {
                    "name": "StaffPass Payroll Payable",
                    "code": "SP2100",
                    "account_type": "liability_current",
                    "company_ids": [Command.set(cls.company.ids)],
                }
            )
        )
        cls.journal = cls.env["account.journal"].create(
            {
                "name": "StaffPass Payroll",
                "code": "SPAY",
                "type": "general",
                "company_id": cls.company.id,
            }
        )
        cls.company.write(
            {
                "staffpass_connector_enabled": True,
                "staffpass_external_id": "company-test",
                "staffpass_journal_id": cls.journal.id,
            }
        )
        cls.user = (
            cls.env["res.users"]
            .with_context(no_reset_password=True)
            .create(
                {
                    "name": "StaffPass Integration Test",
                    "login": "staffpass-integration-test",
                    "company_id": cls.company.id,
                    "company_ids": [Command.set(cls.company.ids)],
                    "group_ids": [
                        Command.set(
                            [
                                cls.env.ref("base.group_user").id,
                                cls.env.ref(
                                    "staffpass_payroll_connector.group_staffpass_integration"
                                ).id,
                            ]
                        )
                    ],
                }
            )
        )
        cls.bridge = cls.env["staffpass.payroll.bridge"].with_user(cls.user)
        cls.payload = {
            "contractVersion": "1.0.0",
            "companyId": "company-test",
            "exportJobId": "payroll-2026-09-a",
            "journalType": "ACCRUAL",
            "entryDate": "2026-09-15",
            "reference": "StaffPass payroll 2026-09-A",
            "currency": cls.company.currency_id.name,
            "lines": [
                {
                    "lineRef": "base:D",
                    "lineOrder": 0,
                    "side": "DEBIT",
                    "accountCode": "SP6100",
                    "costCenterCode": None,
                    "conceptCode": "BASE",
                    "amount": "100.00",
                    "currency": cls.company.currency_id.name,
                    "sourceLineRefs": ["run-a:employee-a:base"],
                    "description": "Base salary",
                },
                {
                    "lineRef": "base:C",
                    "lineOrder": 1,
                    "side": "CREDIT",
                    "accountCode": "SP2100",
                    "costCenterCode": None,
                    "conceptCode": "BASE",
                    "amount": "100.00",
                    "currency": cls.company.currency_id.name,
                    "sourceLineRefs": ["run-a:employee-a:base"],
                    "description": "Payroll payable",
                },
            ],
            "totalDebit": "100.00",
            "totalCredit": "100.00",
            "balanced": True,
            "sourceHash": "sha256:synthetic-source",
            "reversalOf": None,
        }

    def test_import_is_draft_balanced_and_idempotent(self):
        first = self.bridge.import_journal(self.payload)
        second = self.bridge.import_journal(deepcopy(self.payload))

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["moveId"], second["moveId"])
        self.assertEqual(first["externalId"], "payroll-2026-09-a:ACCRUAL")
        move = self.env["account.move"].browse(first["moveId"])
        self.assertEqual(move.state, "draft")
        self.assertEqual(move.company_id, self.company)
        self.assertEqual(move.journal_id, self.journal)
        self.assertEqual(sum(move.line_ids.mapped("debit")), 100.0)
        self.assertEqual(sum(move.line_ids.mapped("credit")), 100.0)

    def test_same_external_id_with_changed_payload_is_rejected(self):
        self.bridge.import_journal(self.payload)
        changed = deepcopy(self.payload)
        changed["reference"] = "Changed after import"
        with self.assertRaises(ValidationError):
            self.bridge.import_journal(changed)

    def test_unbalanced_and_unknown_accounts_fail_closed(self):
        unbalanced = deepcopy(self.payload)
        unbalanced["lines"][1]["amount"] = "99.00"
        with self.assertRaises(ValidationError):
            self.bridge.import_journal(unbalanced)

        unknown = deepcopy(self.payload)
        unknown["exportJobId"] = "payroll-unknown-account"
        unknown["lines"][0]["accountCode"] = "MISSING"
        with self.assertRaises(ValidationError):
            self.bridge.import_journal(unknown)

    def test_reversal_is_idempotent(self):
        imported = self.bridge.import_journal(self.payload)
        first = self.bridge.reverse_journal(
            "company-test",
            "payroll-2026-09-a:ACCRUAL",
            "payroll-2026-09-a-reversal",
            "2026-09-16",
            "Correction approved",
        )
        second = self.bridge.reverse_journal(
            "company-test",
            "payroll-2026-09-a:ACCRUAL",
            "payroll-2026-09-a-reversal",
            "2026-09-16",
            "Correction approved",
        )
        self.assertNotEqual(imported["moveId"], first["moveId"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["moveId"], second["moveId"])
