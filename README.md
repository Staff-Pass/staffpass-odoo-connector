# StaffPass Payroll Journal Bridge for Odoo

Official Odoo addon that receives canonical payroll journals from StaffPass and creates reviewable draft journal entries in Odoo.

## Compatibility

| Odoo | Branch | Addon version | Transport |
| --- | --- | --- | --- |
| 19.0 | `19.0` | `19.0.1.0.0` | JSON-2 `/json/2/staffpass.payroll.bridge/*` |
| 18.0 | `18.0` | `18.0.1.0.0` | Legacy authenticated RPC |

Use the branch matching the target Odoo major version. Odoo 19 uses JSON-2; Odoo 18 exposes the same model methods through its authenticated legacy RPC API.

## What the addon does

- exposes one transactional model method for importing a complete journal;
- creates only draft `account.move` records;
- validates company, currency, date, accounts, analytic cost centers and totals;
- isolates every request to an explicitly configured Odoo company;
- serializes concurrent imports with a PostgreSQL transaction lock;
- returns the original result when an identical external journal is delivered again;
- rejects reuse of an external ID with changed content;
- records a durable audit row without storing employee payroll details;
- creates idempotent reversal drafts without changing the original move.

It does not calculate payroll, post accounting moves, store StaffPass credentials, expose a public unauthenticated controller or replace accounting approval.

## Odoo configuration

1. Install **Payroll Journal Bridge**.
2. Open the target company and select the **StaffPass** tab.
3. Enable imports, enter the immutable StaffPass company ID and select a dedicated general journal.
4. Create a dedicated Odoo bot user, grant the **StaffPass Integration / Integration User** privilege and generate an API key.
5. Give that user access only to the companies that StaffPass may synchronize.

External API access requires an Odoo Custom plan. Odoo Online cannot install Python third-party addons; use Odoo.sh or an on-premise deployment.

## Integration methods

The addon exposes these authenticated model methods:

- `staffpass.payroll.bridge/get_catalog`
- `staffpass.payroll.bridge/import_journal`
- `staffpass.payroll.bridge/get_journal_status`
- `staffpass.payroll.bridge/reverse_journal`

On Odoo 18 call them with `execute_kw` through the authenticated external RPC API, using a dedicated integration user and API key. Do not send a user password or place credentials in the URL. The Odoo 19 branch instead uses JSON-2 with a bearer API key.

## Installation

Copy `staffpass_payroll_connector` into an Odoo addons directory, update the Apps list, then install **Payroll Journal Bridge**. For CLI installations:

```bash
odoo-bin -d DATABASE -i staffpass_payroll_connector --stop-after-init
```

Back up the database and filestore before every upgrade. Upgrade with `-u staffpass_payroll_connector` and restore the matching database, filestore and code commit together for rollback.

## Validation

```bash
python3 tools/validate_addon.py
python3 -m compileall -q staffpass_payroll_connector tools
ruff check .
```

The repository also contains Odoo `TransactionCase` coverage for balanced imports, idempotency, payload conflicts, missing accounts and reversal idempotency. A green static check does not replace installation on the exact Odoo edition and deployment target.

## Odoo Apps publication

The addon includes the required manifest, real PNG icon, HTML description, screenshots, LGPL-3 license and support metadata. Register this Git repository in the Odoo Apps vendor dashboard only after the installation workflow for the target branch is green. Store publication itself requires the StaffPass Odoo vendor account and acceptance of Odoo's publisher terms.

## License

LGPL-3. The StaffPass name and artwork remain trademarks of their owner; the license does not grant trademark rights.
