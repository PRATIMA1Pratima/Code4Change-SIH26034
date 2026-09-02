"""
Phase 7 verification — unit + end-to-end tests.
Run from backend/: python test_compliance_phase7.py
Deleted after verification.
"""
import sys, pprint
sys.path.insert(0, ".")

from app.services.compliance_engine import (
    check_compliance,
    run_compliance_pipeline,
    get_compliance_rules,
    extract_declarations,
    COMPLIANCE_RULES,
)

ok = True
def chk(label, got, want, *, approx=False, contains=False):
    global ok
    if approx:
        passed = abs(float(got) - float(want)) < 0.01
    elif contains:
        passed = str(want).lower() in str(got or "").lower()
    else:
        passed = got == want
    sym = "PASS" if passed else "FAIL"
    if not passed:
        ok = False
        print(f"  {sym}  {label}")
        print(f"        expected : {want!r}")
        print(f"        got      : {got!r}")
    else:
        val = str(got)[:72]
        print(f"  {sym}  {label}  →  {val!r}")

# ═══════════════════════════════════════════════════════════════════════
# 1. FULL COMPLIANT LABEL  (all 6 required fields present + valid)
# ═══════════════════════════════════════════════════════════════════════
print("=== Case 1: Full compliant label ===")

FULL_TEXT = (
    "PRODUCT: Test Biscuits\n\n"
    "MRP Rs. 50/-\n\n"
    "Net Wt. 100g\n\n"
    "Mfg by: ABC Foods Pvt. Ltd.\n"
    "Address: 12 Industrial Area, Mumbai 400001\n"
    "Mfg Date: 01/2026\n\n"
    "Consumer Care: 1800-123-456\n"
    "Email: care@abcfoods.in\n\n"
    "FSSAI Lic. No. 12345678901234"
)
r1 = run_compliance_pipeline(FULL_TEXT)
chk("score == 100.0",   r1["compliance_score"], 100.0)
chk("status COMPLIANT", r1["status"], "COMPLIANT")
chk("no violations",    len(r1["violations"]), 0)
# declaration_status: all required fields valid
for key in ["mrp","net_quantity","manufacturer","address","manufacturing_date","consumer_care"]:
    ds = r1["declaration_status"][key]
    chk(f"  {key}.found", ds["found"], True)
    chk(f"  {key}.valid", ds["valid"], True)

# ═══════════════════════════════════════════════════════════════════════
# 2. MISSING TWO FIELDS  (no MRP, no consumer_care)
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Case 2: Missing MRP + consumer care ===")

MISSING_TEXT = (
    "Net Wt. 100g\n"
    "Mfg by: XYZ Corp Ltd.\n"
    "Address: 45 Park Road, Delhi 110001\n"
    "Mfg Date: 03/2025\n"
)
r2 = run_compliance_pipeline(MISSING_TEXT)
# max_points = 6 × 1.0 = 6.0
# passed     = 4 × 1.0 = 4.0  → 66.67%
chk("score ≈ 66.67",    r2["compliance_score"], 66.67, approx=True)
chk("status NON_COMPLIANT", r2["status"], "NON_COMPLIANT")
# 2 MISSING (mrp + consumer_care) + 1 WARNING (product_name not in text)
chk("3 violations total",   len(r2["violations"]), 3)
chk("mrp violation is MISSING", r2["violations"][0], "[MISSING]", contains=True)
chk("care violation is MISSING",
    any("[MISSING]" in v and "Consumer Care" in v for v in r2["violations"]), True)

# ═══════════════════════════════════════════════════════════════════════
# 3. INVALID MRP  (non-numeric amount)
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Case 3: Invalid MRP value (zero amount) ===")

# Give check_compliance an MRP that passes regex extraction but fails validation
d3 = extract_declarations("MRP Rs. 100g")  # OCR might mangle the amount
# Directly test check_compliance with a clearly invalid MRP
decls3 = {
    "mrp": "MRP Rs. 0",   # present but zero — should fail validator
    "net_quantity": "Net Wt. 200g",
    "manufacturer": "ABC Foods Pvt. Ltd.",
    "address": "12 Some Road, Bengaluru 560001",
    "manufacturing_date": "02/2025",
    "consumer_care": "Consumer Care: 1800-999-888",
    "product_name": "Test Product",
}
r3 = check_compliance(decls3)
chk("mrp.found=True",  r3["declaration_status"]["mrp"]["found"], True)
chk("mrp.valid=False", r3["declaration_status"]["mrp"]["valid"], False)
chk("[INVALID] in mrp violation", r3["violations"][0], "[INVALID]", contains=True)
# Score: mrp earns 0.0 (hard fail), 5 others earn 1.0 each → 5/6 ≈ 83.33
chk("score ≈ 83.33",   r3["compliance_score"], 83.33, approx=True)
chk("NON_COMPLIANT",   r3["status"], "NON_COMPLIANT")

# ═══════════════════════════════════════════════════════════════════════
# 4. INVALID DATE  (year out of range)
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Case 4: Invalid manufacturing date (year 1999) ===")

decls4 = {
    "mrp": "MRP Rs. 50/-",
    "net_quantity": "Net Wt. 100g",
    "manufacturer": "ABC Foods Pvt. Ltd.",
    "address": "12 Some Road, Mumbai 400001",
    "manufacturing_date": "01/1999",   # too old
    "consumer_care": "Consumer Care: 1800-123-456",
    "product_name": "Test Product",
}
r4 = check_compliance(decls4)
chk("date.found=True",  r4["declaration_status"]["manufacturing_date"]["found"], True)
chk("date.valid=False", r4["declaration_status"]["manufacturing_date"]["valid"], False)
chk("[INVALID] in date violation", r4["violations"][0], "[INVALID]", contains=True)
chk("score ≈ 83.33",    r4["compliance_score"], 83.33, approx=True)

# ═══════════════════════════════════════════════════════════════════════
# 5. PRODUCT_NAME WARNING  (informational field, weight 0.5)
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Case 5: product_name missing (warning only, score unaffected) ===")

decls5 = {
    "mrp": "MRP Rs. 50/-",
    "net_quantity": "Net Wt. 100g",
    "manufacturer": "ABC Foods Pvt. Ltd.",
    "address": "12 Some Road, Mumbai 400001",
    "manufacturing_date": "01/2026",
    "consumer_care": "Consumer Care: 1800-123-456",
    "product_name": None,   # missing — WARNING severity, not required
}
r5 = check_compliance(decls5)
# product_name is NOT required → does not reduce score
chk("score == 100.0",          r5["compliance_score"], 100.0)
chk("status COMPLIANT",        r5["status"], "COMPLIANT")
# product_name missing → [WARNING] (non-required field)
warning_msgs = [v for v in r5["violations"] if "[WARNING]" in v]
chk("product_name [WARNING] present", len(warning_msgs), 1)
# No [MISSING] or [INVALID] errors (all required fields are present+valid)
error_msgs = [v for v in r5["violations"] if "[MISSING]" in v or "[INVALID]" in v]
chk("no ERROR/MISSING violations", len(error_msgs), 0)

# ═══════════════════════════════════════════════════════════════════════
# 6. EMPTY TEXT  (all fields None)
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Case 6: Empty OCR text ===")

r6 = run_compliance_pipeline("")
chk("score == 0.0",     r6["compliance_score"], 0.0)
chk("NON_COMPLIANT",    r6["status"], "NON_COMPLIANT")
# 6 required fields → [MISSING], 1 non-required (product_name) → [WARNING]
chk("6 MISSING violations", len([v for v in r6["violations"] if "[MISSING]" in v]), 6)
chk("1 WARNING violation",  len([v for v in r6["violations"] if "[WARNING]" in v]), 1)

# ═══════════════════════════════════════════════════════════════════════
# 7. get_compliance_rules() structure
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Case 7: get_compliance_rules() ===")

rules = get_compliance_rules()
chk("returns 7 rules",    len(rules), 7)
chk("first key is mrp",   rules[0]["key"], "mrp")
chk("mrp required=True",  rules[0]["required"], True)
chk("mrp weight=1.0",     rules[0]["weight"], 1.0)
chk("mrp severity=ERROR", rules[0]["severity"], "ERROR")
chk("mrp has_validator=True", rules[0]["has_validator"], True)

# product_name is last, not required, weight 0.5
pn_rule = next(r for r in rules if r["key"] == "product_name")
chk("product_name required=False", pn_rule["required"], False)
chk("product_name weight=0.5",     pn_rule["weight"], 0.5)
chk("product_name severity=WARNING", pn_rule["severity"], "WARNING")

# ═══════════════════════════════════════════════════════════════════════
# 8. SCORING ARITHMETIC  (spot-check formula)
# ═══════════════════════════════════════════════════════════════════════
print("\n=== Case 8: Scoring arithmetic ===")

# 3 of 6 required fields present+valid → 3/6 = 50%
decls8 = {
    "mrp": "MRP Rs. 50/-",
    "net_quantity": "Net Wt. 100g",
    "manufacturer": "ABC Foods Pvt. Ltd.",
    "address": None,
    "manufacturing_date": None,
    "consumer_care": None,
    "product_name": None,
}
r8 = check_compliance(decls8)
chk("3/6 fields → score 50.0", r8["compliance_score"], 50.0)
chk("NON_COMPLIANT",           r8["status"], "NON_COMPLIANT")
# 3 required missing + 1 WARNING for product_name
chk("3 MISSING violations",    len([v for v in r8["violations"] if "[MISSING]" in v]), 3)
chk("1 WARNING violation",     len([v for v in r8["violations"] if "[WARNING]" in v]), 1)

# ═══════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("ALL PHASE 7 UNIT TESTS PASSED" if ok else "SOME TESTS FAILED — see above")
print("=" * 60)
sys.exit(0 if ok else 1)
