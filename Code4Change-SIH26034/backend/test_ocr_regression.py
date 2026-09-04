"""Regression checks for field-aware OCR candidate selection.

Run from backend/:  python test_ocr_regression.py
"""

from app.services.compliance_engine import run_compliance_pipeline


LAY_LABEL_CANDIDATES = [
    {
        "source": "processed", "image": "label_proc.png", "psm": 6,
        "text": "snp As. 36.00 NOL. OF ALL TINE)\nN.QTY:\nMFD:",
    },
    {
        "source": "original", "image": "label.jpg", "psm": 3,
        "text": (
            "MRP Ps. 35.00 (INCL. OF ALL TAXES)\n"
            "Sankrail, Distt Howrah, Pin-711302, West Bengal\n"
            "OR CALL US AT 1800 22 4020"
        ),
    },
    {
        "source": "original", "image": "label.jpg", "psm": 11,
        "text": "Manufactured by: PEPSICO INDIA HOLDINGS PVT. LTD.\nMFD:",
    },
]


result = run_compliance_pipeline("", LAY_LABEL_CANDIDATES)
fields = result["detected_declarations"]
states = result["declaration_status"]

assert fields["mrp"] == "MRP Ps. 35.00"
assert fields["manufacturer"] == "PEPSICO INDIA HOLDINGS PVT. LTD."
assert "711302" in (fields["address"] or "")
assert "1800 22 4020" in (fields["consumer_care"] or "")
assert fields["product_name"] is None
assert states["net_quantity"]["state"] == "UNREADABLE"
assert states["manufacturing_date"]["state"] == "UNREADABLE"

print("OCR regression checks passed")
