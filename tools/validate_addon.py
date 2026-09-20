#!/usr/bin/env python3
import ast
import pathlib
import struct
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADDON = ROOT / "staffpass_payroll_connector"
failures = []


def fail(message):
    failures.append(message)


manifest_path = ADDON / "__manifest__.py"
manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
required = {"name", "summary", "version", "license", "depends", "data", "images"}
missing = required.difference(manifest)
if missing:
    fail(f"manifest missing fields: {sorted(missing)}")
if manifest.get("version") != "18.0.1.0.0":
    fail("manifest version must target Odoo 18.0")
if manifest.get("license") != "LGPL-3":
    fail("manifest license must be LGPL-3")
if manifest.get("depends") != ["account"]:
    fail("the addon must declare its complete minimal dependency on account")

for relative in manifest.get("data", []):
    path = ADDON / relative
    if not path.is_file():
        fail(f"manifest data file missing: {relative}")
    elif path.suffix == ".xml":
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            fail(f"invalid XML {relative}: {exc}")

for relative in manifest.get("images", []):
    path = ADDON / relative
    if not path.is_file():
        fail(f"manifest image missing: {relative}")

for path in ADDON.rglob("*.xml"):
    try:
        ET.parse(path)
    except ET.ParseError as exc:
        fail(f"invalid XML {path.relative_to(ROOT)}: {exc}")

for name in ("icon.png", "main_screenshot.png", "configuration.png", "audit_log.png"):
    path = ADDON / "static" / "description" / name
    if not path.is_file():
        fail(f"store asset missing: {name}")
        continue
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        fail(f"store asset is not a real PNG: {name}")
        continue
    width, height = struct.unpack(">II", data[16:24])
    if name == "icon.png" and (width, height) != (512, 512):
        fail("icon.png must be 512x512")
    if name == "main_screenshot.png" and width < 1200:
        fail("main_screenshot.png must be a real cover image")

description = (ADDON / "static" / "description" / "index.html").read_text(encoding="utf-8")
if "<script" in description.lower():
    fail("Odoo Apps description cannot contain JavaScript")
for forbidden in ("github.com", "apps.apple.com", "play.google.com"):
    if forbidden in description.lower():
        fail(f"Odoo Apps description contains forbidden external promotion: {forbidden}")

if failures:
    print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
    raise SystemExit(1)
print("Validated Odoo 18 addon structure, XML, manifest and store assets.")
