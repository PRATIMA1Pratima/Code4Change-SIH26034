"""
services/compliance_engine.py – Declaration extraction and compliance checking.

Architecture
------------
1. ``extract_declarations(text)``     – regex-based field detection  (Phase 6)
2. ``check_compliance(declarations)`` – rule-based weighted scoring   (Phase 7)
3. ``run_compliance_pipeline(text)``  – convenience wrapper
4. ``get_compliance_rules()``         – introspection helper

Rule system (Phase 7)
---------------------
Each declaration is governed by a ``ComplianceRule`` dataclass that holds:
  - ``label``     : human-readable display name
  - ``required``  : True = missing counts against the score
  - ``weight``    : how much this field contributes to the score
                    required fields = 1.0, informational fields = 0.5
  - ``severity``  : "ERROR" (legally required) | "WARNING" (best-practice)
  - ``validator`` : optional callable(value: str) → str | None
                    returns None when valid, an error description when invalid

Scoring formula
---------------
  max_points  = sum(rule.weight for rule in rules if rule.required)
  earned      = sum(rule.weight × field_pass_factor for each required rule)
  score       = round(earned / max_points × 100, 2)

  field_pass_factor:
    1.0  – field present AND valid (or has no validator)
    0.5  – field present BUT validator returned a warning (soft fail)
    0.0  – field missing OR validator returned an error

Violation message format
------------------------
  [MISSING]  <Label> – declaration not detected on the label
  [INVALID]  <Label> – <validator error message>
  [WARNING]  <Label> – <validator warning message>
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

from app.config import COMPLIANCE_THRESHOLD

# ── Required declarations ─────────────────────────────────────────────────────

REQUIRED_DECLARATIONS: list[str] = [
    "mrp",
    "net_quantity",
    "manufacturer",
    "address",
    "manufacturing_date",
    "consumer_care",
]

DECLARATION_LABELS: dict[str, str] = {
    "mrp":                "MRP (Maximum Retail Price)",
    "net_quantity":       "Net Quantity",
    "manufacturer":       "Manufacturer / Packer Name",
    "address":            "Manufacturer / Packer Address",
    "manufacturing_date": "Manufacturing / Packing Date",
    "consumer_care":      "Consumer Care Information",
    "product_name":       "Product Name",
}


# ═════════════════════════════════════════════════════════════════════════════
# RULE SYSTEM
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ComplianceRule:
    """Defines how a single declaration field is evaluated."""

    key:       str                              # matches DECLARATION_LABELS key
    label:     str                              # display name
    required:  bool        = True               # counts toward score
    weight:    float       = 1.0               # contribution to max score
    severity:  str         = "ERROR"           # ERROR | WARNING
    validator: Callable[[str], str | None] | None = field(
        default=None, repr=False
    )
    description: str = ""                      # what this rule checks


# ── Field validators ──────────────────────────────────────────────────────────
# Each returns None when the value passes, or a short error string when it fails.

def _validate_mrp(value: str) -> str | None:
    """MRP must contain a positive numeric amount."""
    nums = re.findall(r"\d[\d,]*(?:\.\d{1,2})?", value)
    if not nums:
        return "No numeric amount found in MRP value"
    amount_str = nums[0].replace(",", "")
    try:
        amount = float(amount_str)
    except ValueError:
        return f"Could not parse MRP amount: {amount_str!r}"
    if amount <= 0:
        return f"MRP amount must be greater than zero (got {amount})"
    return None


def _validate_net_quantity(value: str) -> str | None:
    """Net quantity must contain a number and a recognised unit."""
    has_number = bool(re.search(r"\d", value))
    # Use lookahead/lookbehind instead of \b so units directly appended to
    # digits work correctly: "100g", "250gm", "1L", "500ml".
    has_unit   = bool(re.search(
        r"(?<![A-Za-z])(kg|gm|g|mg|ltr|litres?|liters?|ml|cl|l|oz|lb|"
        r"pcs|pieces?|tabs?|capsules?|units?|nos?)(?![A-Za-z])",
        value, re.IGNORECASE
    ))
    if not has_number:
        return "No numeric quantity found"
    if not has_unit:
        return "No recognised unit found (e.g. g, kg, ml, pcs)"
    return None


def _validate_manufacturer(value: str) -> str | None:
    """Manufacturer name must be at least 3 characters and contain a letter."""
    stripped = value.strip()
    if len(stripped) < 3:
        return "Manufacturer name is too short (minimum 3 characters)"
    if not re.search(r"[A-Za-z]", stripped):
        return "Manufacturer name must contain at least one letter"
    return None


def _validate_address(value: str) -> str | None:
    """Address should be at least 10 characters and ideally contain a PIN or city."""
    stripped = value.strip()
    if len(stripped) < 10:
        return "Address is too short (minimum 10 characters)"
    # Soft check: warn if no PIN code found (not mandatory to fail the rule)
    if not re.search(r"\b\d{6}\b", stripped):
        # Return None (pass) — PIN absence is a warning surfaced separately
        pass
    return None


def _validate_manufacturing_date(value: str) -> str | None:
    """Date must contain a year in a plausible range (2000–2035)."""
    years = re.findall(r"\b(20[0-2]\d|19\d\d)\b", value)
    if not years:
        return "No valid year found in manufacturing date"
    year = int(years[0])
    if year < 2000:
        return f"Manufacturing year {year} seems too old (before 2000)"
    if year > 2035:
        return f"Manufacturing year {year} seems implausible (after 2035)"
    return None


def _validate_consumer_care(value: str) -> str | None:
    """Consumer care must contain a phone number or email address."""
    has_phone = bool(re.search(
        r"(?:\+91[\s\-]?)?\d[\d\s\-]{7,14}\d", value
    ))
    has_email = bool(re.search(
        r"[\w\.\+\-]+@[\w\.\-]+\.[a-z]{2,6}", value, re.IGNORECASE
    ))
    if not has_phone and not has_email:
        return "Consumer care must include a phone number or email address"
    return None


def _validate_product_name(value: str) -> str | None:
    """Product name must be at least 2 characters."""
    if len(value.strip()) < 2:
        return "Product name is too short"
    return None


# ── Rule registry ─────────────────────────────────────────────────────────────
# Order determines display order in the UI.

COMPLIANCE_RULES: list[ComplianceRule] = [
    ComplianceRule(
        key="mrp",
        label=DECLARATION_LABELS["mrp"],
        required=True, weight=1.0, severity="ERROR",
        validator=_validate_mrp,
        description="MRP (Maximum Retail Price) must be declared with a positive numeric value",
    ),
    ComplianceRule(
        key="net_quantity",
        label=DECLARATION_LABELS["net_quantity"],
        required=True, weight=1.0, severity="ERROR",
        validator=_validate_net_quantity,
        description="Net quantity must be declared with a numeric value and recognised unit",
    ),
    ComplianceRule(
        key="manufacturer",
        label=DECLARATION_LABELS["manufacturer"],
        required=True, weight=1.0, severity="ERROR",
        validator=_validate_manufacturer,
        description="Name of the manufacturer or packer must be declared",
    ),
    ComplianceRule(
        key="address",
        label=DECLARATION_LABELS["address"],
        required=True, weight=1.0, severity="ERROR",
        validator=_validate_address,
        description="Full postal address of the manufacturer or packer must be declared",
    ),
    ComplianceRule(
        key="manufacturing_date",
        label=DECLARATION_LABELS["manufacturing_date"],
        required=True, weight=1.0, severity="ERROR",
        validator=_validate_manufacturing_date,
        description="Manufacturing or packing date must be declared with a valid year",
    ),
    ComplianceRule(
        key="consumer_care",
        label=DECLARATION_LABELS["consumer_care"],
        required=True, weight=1.0, severity="ERROR",
        validator=_validate_consumer_care,
        description="Consumer care contact (phone or email) must be provided",
    ),
    ComplianceRule(
        key="product_name",
        label=DECLARATION_LABELS["product_name"],
        required=False, weight=0.5, severity="WARNING",
        validator=_validate_product_name,
        description="Product name should be clearly stated on the label (best practice)",
    ),
]

# Fast lookup: key → rule
_RULE_BY_KEY: dict[str, ComplianceRule] = {r.key: r for r in COMPLIANCE_RULES}


# ── Text normalisation ────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


# ═════════════════════════════════════════════════════════════════════════════
# COMPILED PATTERNS
# Each section has a brief note on what variations it handles.
# ═════════════════════════════════════════════════════════════════════════════

# ── MRP ───────────────────────────────────────────────────────────────────────
# Handles:
#   MRP Rs. 50/-   MRP: ₹50   M.R.P Rs 50.00   MRP INR 50
#   Maximum Retail Price Rs. 50
#   OCR noise: "Rs" read as "Ps", "Bs", "Rs." — we keep the full matched string
_MRP_RE = re.compile(
    r"""
    (?:
        m\.?r\.?p\.?                          # MRP / M.R.P.
        |
        max(?:imum)?\s+retail\s+price         # Maximum Retail Price
    )
    \s*[:\-]?\s*                              # optional separator
    (?:rs\.?|₹|inr|ps\.?|bs\.?|re\.?)?\s*   # currency prefix (OCR tolerant)
    (\d[\d,]*(?:\.\d{1,2})?)\s*(?:/-)?       # amount  e.g. 50  50.00  50/-
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ── Net Quantity ──────────────────────────────────────────────────────────────
# Handles:
#   Net Wt. 100g   Net Weight: 500 ml   Net Qty 250gm
#   Net Vol. 1L    Net Content 200g     Net 100g
#   OCR: "Wt" often read as "Wt." or "wt" — all covered
_NET_QTY_RE = re.compile(
    r"""
    (?:
        net\s*
        (?:
            w(?:ei)?g?h?t\.?          # weight / wt. / wgt
            |wt\.?
            |qty\.?
            |quantit(?:y)?\.?
            |vol(?:ume)?\.?
            |content\.?
            |contents?\.?
        )?
    )
    \s*[:\-]?\s*
    (\d+(?:\.\d+)?\s*            # numeric value
    (?:
        kg|gm|g\b|mg|            # mass
        ltr|litre|liter|ml|cl|l\b|  # volume
        oz|lb|                   # imperial
        pcs|pieces?|tabs?|capsules?|units?|nos?\.?  # count
    ))
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ── Manufacturer / Packer ─────────────────────────────────────────────────────
# Handles:
#   Mfg by: ABC Foods Pvt. Ltd.
#   Manufactured by: XYZ Corp
#   Packed by: ABC Industries
#   Marketed by: ABC Co.
#   Mfr: ABC   Packer: ABC Foods
_MFG_RE = re.compile(
    r"""
    (?:
        m(?:a(?:nu)?)?f(?:a(?:ctu(?:red?|ring))?)?g?\.?\s*(?:by)? # Mfg/Mfr/Manufactured
        |pack(?:ed|er)?\.?\s*(?:by)?                               # Packed/Packer
        |marketed\s+by                                             # Marketed by
        |imported\s+by                                             # Imported by
        |manufactured\s+(?:and\s+)?packed\s+by
    )
    \s*[:\-]?\s*
    ([A-Z][A-Za-z0-9 ,\.&\-\']+?              # company name
    (?:
        pvt\.?\s*ltd\.?
        |private\s+limited
        |ltd\.?
        |llp
        |inc\.?
        |corp\.?
        |co\.?
        |industries
        |foods?
        |enterprises?
        |traders?
        |international
    ))
    (?=\s*[\n,]|$)                            # stop at newline or comma
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ── Address ───────────────────────────────────────────────────────────────────
# Strategy: look for the keyword "Address" / "Add." then capture the rest of
# that line.  Also fall back to detecting a PIN code (6-digit Indian postal
# code) on any line, which is a strong address indicator.
_ADDR_KEYWORD_RE = re.compile(
    r"""
    (?:address|addr|add)\.?\s*[:\-]?\s*
    (.{10,120})                   # at least 10 chars of address content
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ADDR_PINCODE_RE = re.compile(
    r"""
    ([A-Za-z0-9 ,\-\.]+          # street / area name
    \b\d{6}\b                    # 6-digit PIN code
    (?:\s*,\s*[A-Za-z ]+)?)      # optional state/country after PIN
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ── Manufacturing / Packing Date ──────────────────────────────────────────────
# Handles all common Indian label date formats:
#   Mfg Date: 01/2026       Mfg. Date: Jan 2026
#   Mfg: 01-2026            Manufacturing Date: 2026-01
#   Pkd: 01/01/2026         Mfg/Exp: 01/2026
#   Best Before: 6 months   (captured as-is)
_DATE_RE = re.compile(
    r"""
    (?:
        m(?:a(?:nu(?:facturing|factured)?)?)?f(?:g|r)?\.?   # Mfg/Mfr/Manu...
        |pack(?:ed|ing|ed\s+on)?\.?
        |p(?:kd|acked)?\.?
        |mfd\.?
        |manuf\.?
        |production\s+date
        |date\s+of\s+(?:mfg|manufacture|packing|packaging|production)
        |(?:mfg|mfr)\.?/exp\.?                              # Mfg/Exp combos
    )
    \s*(?:date)?\.?\s*[:\-]?\s*
    (
        (?:\d{1,2}[\/\-\.])?                   # optional day
        (?:\d{1,2}|                            # numeric month
           jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|
           apr(?:il)?|may|jun(?:e)?|
           jul(?:y)?|aug(?:ust)?|sep(?:tember)?|
           oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)
        [\/\-\.\s]
        \d{2,4}                                # year
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ── Consumer Care ─────────────────────────────────────────────────────────────
# Handles:
#   Consumer Care: 1800-123-456
#   Consumer Helpline: 1800 123 4567
#   Customer Care No.: +91-9876543210
#   Toll Free: 1800XXXXXXX
#   care@company.in   helpline@company.in
_CONSUMER_PHONE_RE = re.compile(
    r"""
    (?:
        consumer\s*(?:care|helpline|services?|complaints?)?
        |customer\s*(?:care|helpline|services?|support)?
        |help\s*(?:line|desk)?
        |toll[\s\-]?free
        |care\s*(?:no|number|no\.)?
    )
    \s*[:\-]?\s*
    (
        (?:\+91[\s\-]?)?                      # optional country code
        (?:1800[\s\-]?\d{3,7}[\s\-]?\d{0,4}  # 1800 toll-free
           |\d{3,5}[\s\-]\d{3,4}[\s\-]?\d{0,4}  # landline / mobile
           |\d{10,13})                        # plain 10-digit
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_CONSUMER_EMAIL_RE = re.compile(
    r"""
    (?:
        consumer\s*(?:care|helpline|services?|email)?
        |customer\s*(?:care|email)?
        |email\s*(?:us)?
        |e[\s\-]?mail
        |contact
    )
    \s*[:\-]?\s*
    ([\w\.\+\-]+@[\w\.\-]+\.[a-z]{2,6})      # email address
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Standalone email on its own line (no keyword prefix) — lower priority
_STANDALONE_EMAIL_RE = re.compile(
    r"^[^\S\n]*"                              # optional leading whitespace
    r"([\w\.\+\-]+@[\w\.\-]+\.[a-z]{2,6})"   # email
    r"[^\S\n]*$",
    re.IGNORECASE | re.MULTILINE,
)

# ── Product Name ─────────────────────────────────────────────────────────────
# Strategy: look for "Product:" / "Product Name:" keyword first.
# Fall back to: first non-empty line that is NOT a known declaration keyword.
_PRODUCT_KEYWORD_RE = re.compile(
    r"product(?:\s*name)?\s*[:\-]\s*(.+)",
    re.IGNORECASE,
)

# Lines that are definitely NOT product names
_NON_PRODUCT_LINE_RE = re.compile(
    r"""
    ^\s*(?:
        m\.?r\.?p|mrp|max(?:imum)?\s+retail |  # MRP
        net\s*(?:wt|wt\.|weight|qty|vol)|       # Net qty
        m(?:fg|fgd|anuf)|packed|packer|         # Manufacturer
        address|addr|add\.|                      # Address
        mfg\s*date|manufacturing\s*date|pkd|     # Date
        consumer|customer|toll|helpline|email|  # Consumer care
        best\s*before|expiry|exp\.|use\s*by|    # Expiry
        fssai|lic\.|batch|lot|                  # FSSAI/Batch
        ingredients|contains|allergen|          # Ingredients
        barcode|ean|isbn|                        # Barcodes
        \d{10,}                                  # Long number-only lines
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


# ═════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL EXTRACTOR FUNCTIONS
# Each returns a string (matched value) or None.
# ═════════════════════════════════════════════════════════════════════════════

def _extract_mrp(text: str) -> str | None:
    m = _MRP_RE.search(text)
    if m:
        # Return the full matched span trimmed, not just the numeric group,
        # so the UI shows "Rs. 50/-" rather than just "50".
        return m.group(0).strip()
    return None


def _extract_net_quantity(text: str) -> str | None:
    m = _NET_QTY_RE.search(text)
    if m:
        return m.group(0).strip()
    return None


def _extract_manufacturer(text: str) -> str | None:
    m = _MFG_RE.search(text)
    if m:
        return m.group(1).strip()
    return None


def _extract_address(text: str) -> str | None:
    # Priority 1: explicit "Address:" keyword
    m = _ADDR_KEYWORD_RE.search(text)
    if m:
        value = m.group(1).strip()
        # Trim at next newline (the keyword line ends there)
        value = value.splitlines()[0].strip()
        if len(value) >= 8:
            return value

    # Priority 2: any line containing a 6-digit PIN code
    m = _ADDR_PINCODE_RE.search(text)
    if m:
        return m.group(0).strip()

    return None


def _extract_manufacturing_date(text: str) -> str | None:
    m = _DATE_RE.search(text)
    if m:
        return m.group(1).strip()
    return None


def _extract_consumer_care(text: str) -> str | None:
    # Priority 1: phone number with consumer-care keyword
    m = _CONSUMER_PHONE_RE.search(text)
    if m:
        return m.group(0).strip()

    # Priority 2: email with consumer-care keyword
    m = _CONSUMER_EMAIL_RE.search(text)
    if m:
        return m.group(0).strip()

    # Priority 3: standalone email address (e.g. "Email: care@abc.in" line)
    m = _STANDALONE_EMAIL_RE.search(text)
    if m:
        # Only accept if the line also contains an "@" — already guaranteed by
        # the pattern, but double-check that the line looks like a contact.
        return m.group(1).strip()

    return None


def _extract_product_name(text: str) -> str | None:
    # Priority 1: explicit "Product:" keyword
    m = _PRODUCT_KEYWORD_RE.search(text)
    if m:
        return m.group(1).strip()

    # Priority 2: first non-empty line that doesn't look like another field
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _NON_PRODUCT_LINE_RE.match(stripped):
            continue
        # Must contain at least one letter and be reasonably short
        if re.search(r"[A-Za-z]", stripped) and len(stripped) <= 80:
            return stripped

    return None


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

def extract_declarations(text: str) -> dict[str, str | None]:
    """Run all extractors over *text* and return a declarations dict.

    Keys match ``DECLARATION_LABELS``.  Value is the extracted string
    (trimmed) or ``None`` if not found.

    Args:
        text: Cleaned OCR text from ``ocr_service.extract_text()``.

    Returns:
        Dict mapping declaration key → value | None.
    """
    if not text or not text.strip():
        return {key: None for key in DECLARATION_LABELS}

    normalised = _normalise(text)

    return {
        "mrp":               _extract_mrp(normalised),
        "net_quantity":      _extract_net_quantity(normalised),
        "manufacturer":      _extract_manufacturer(normalised),
        "address":           _extract_address(normalised),
        "manufacturing_date": _extract_manufacturing_date(normalised),
        "consumer_care":     _extract_consumer_care(normalised),
        "product_name":      _extract_product_name(normalised),
    }


def check_compliance(declarations: dict[str, str | None]) -> dict:
    """Evaluate *declarations* against the COMPLIANCE_RULES registry.

    Scoring
    -------
    Only *required* rules contribute to the score.
    Each required rule can earn 0.0, 0.5, or 1.0 × its weight:
      - 0.0  field missing, or validator returned an ERROR
      - 0.5  field present but validator returned a WARNING (soft fail)
      - 1.0  field present and valid (or has no validator)

    Returns
    -------
    {
      "compliance_score"   : float,      # 0.0 – 100.0
      "status"             : str,        # COMPLIANT | NON_COMPLIANT
      "violations"         : list[str],  # [MISSING]/[INVALID]/[WARNING] messages
      "declaration_status" : dict        # key → {found, valid, severity, value, message}
    }
    """
    max_points:    float = 0.0
    earned_points: float = 0.0
    violations:    list[str] = []
    declaration_status: dict = {}

    for rule in COMPLIANCE_RULES:
        value   = declarations.get(rule.key)
        present = value is not None and str(value).strip() != ""

        # ── Determine this field's pass factor and any violation message ──
        pass_factor: float   = 0.0
        field_valid: bool    = False
        message:     str | None = None

        if not present:
            # Field completely missing — use severity to set message prefix
            prefix  = "[MISSING]" if rule.required else "[WARNING]"
            message = f"{prefix}  {rule.label} – declaration not detected on the label"
        else:
            # Field is present — run validator if one exists
            if rule.validator is not None:
                validation_error = rule.validator(str(value))
                if validation_error is None:
                    # Fully valid
                    pass_factor = 1.0
                    field_valid = True
                else:
                    # Present but invalid — treat as soft-fail (0.5) for
                    # WARNING-severity rules, hard-fail (0.0) for ERROR-severity
                    if rule.severity == "WARNING":
                        pass_factor = 0.5
                        field_valid = False
                        message = f"[WARNING]  {rule.label} – {validation_error}"
                    else:
                        pass_factor = 0.0
                        field_valid = False
                        message = f"[INVALID]  {rule.label} – {validation_error}"
            else:
                # No validator — presence alone is sufficient
                pass_factor = 1.0
                field_valid = True

        # ── Accumulate score only for required rules ──────────────────────
        if rule.required:
            max_points    += rule.weight
            earned_points += rule.weight * pass_factor

        # ── Collect violation message ──────────────────────────────────────
        if message:
            violations.append(message)

        declaration_status[rule.key] = {
            "found":    present,
            "valid":    field_valid,
            "severity": rule.severity,
            "value":    value,
            "message":  message,
        }

    # ── Final score and status ─────────────────────────────────────────────
    score  = round((earned_points / max_points) * 100, 2) if max_points > 0 else 0.0
    status = "COMPLIANT" if score >= COMPLIANCE_THRESHOLD else "NON_COMPLIANT"

    return {
        "compliance_score":   score,
        "status":             status,
        "violations":         violations,
        "declaration_status": declaration_status,
    }


def run_compliance_pipeline(ocr_text: str) -> dict:
    """Convenience wrapper: extract → check → return combined result.

    Args:
        ocr_text: Raw cleaned text from the OCR service.

    Returns:
        Dict with keys: compliance_score, status, violations,
        declaration_status, detected_declarations.
    """
    declarations = extract_declarations(ocr_text)
    result       = check_compliance(declarations)
    result["detected_declarations"] = declarations
    return result


def get_compliance_rules() -> list[dict]:
    """Return the current rule registry as a list of plain dicts.

    Used by the debug endpoint to surface the rule configuration in the API,
    making it easy to understand why a product received a particular score.
    """
    return [
        {
            "key":         r.key,
            "label":       r.label,
            "required":    r.required,
            "weight":      r.weight,
            "severity":    r.severity,
            "description": r.description,
            "has_validator": r.validator is not None,
        }
        for r in COMPLIANCE_RULES
    ]
