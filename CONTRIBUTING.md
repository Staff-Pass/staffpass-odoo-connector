# Contributing

1. Target only the Odoo version named by the branch.
2. Never include credentials, database dumps or real payroll fixtures.
3. Preserve draft-only creation, company isolation and deterministic idempotency.
4. Add an Odoo transaction test for every behavioral change.
5. Run `python3 tools/validate_addon.py`, `python3 -m compileall -q staffpass_payroll_connector tools` and `ruff check .`.
6. Increment the five-part addon version for every release.
