"""
Finance PDF Service

Generates professional fee receipts and invoices for StudentFee and Payment.
Uses WeasyPrint (HTML/CSS → PDF; requires Pango etc. on the system — see backend README).

Key design decisions:
- Layout remains table-based for predictable receipts/invoices across engines.
- School info is fetched from the Tenant model (logo, name, address, phone, tagline).
- `show_note=True`  → footer "auto-generated" note included  (PDF download)
- `show_note=False` → no generated note                      (browser print)
- `for_print=True`  → dual-copy page: OFFICE COPY + STUDENT COPY separated by dashed line
"""

from datetime import datetime
from typing import Optional

from flask import render_template, render_template_string

from core.tenant import get_tenant_id

try:
    from weasyprint import HTML
    HAS_WEASYPRINT = True
except (ImportError, OSError):
    # OSError: native Pango/GTK libs missing (common on macOS before `brew install weasyprint`)
    HAS_WEASYPRINT = False
    HTML = None  # type: ignore[assignment,misc]

from .student_fee_service import get_student_fee


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _html_to_pdf(html: str) -> Optional[bytes]:
    """Convert HTML string to PDF bytes using WeasyPrint."""
    if not HAS_WEASYPRINT or HTML is None:
        return None
    try:
        return HTML(string=html).write_pdf()
    except Exception:
        return None


def _get_tenant_info() -> dict:
    """Fetch current tenant's branding info from DB."""
    try:
        from core.models import Tenant
        tenant_id = get_tenant_id()
        if tenant_id:
            t = Tenant.query.get(tenant_id)
            if t:
                return {
                    "school_name": t.name or "School",
                    "school_address": t.address or "",
                    "school_phone": t.phone or "",
                    "school_email": t.contact_email or "",
                    "school_tagline": t.tagline or "",
                    "school_logo": t.logo_url or "",
                    "board_affiliation": t.board_affiliation or "",
                }
    except Exception:
        pass
    return {
        "school_name": "School ERP",
        "school_address": "",
        "school_phone": "",
        "school_email": "",
        "school_tagline": "",
        "school_logo": "",
        "board_affiliation": "",
    }


def _get_payment_with_student_fee(payment_id: str) -> Optional[dict]:
    """Get payment by ID with student_fee, items, and student context."""
    from modules.finance.models import Payment

    tenant_id = get_tenant_id()
    if not tenant_id:
        return None

    payment = Payment.query.filter_by(id=payment_id, tenant_id=tenant_id).first()
    if not payment:
        return None

    d = payment.to_dict()
    if payment.student_fee:
        sf = payment.student_fee
        d["student_fee"] = sf.to_dict()
        d["student_fee"]["items"] = [i.to_dict() for i in sf.items]
        d["student_fee"]["student_name"] = (
            sf.student.user.name if sf.student and sf.student.user else None
        )
        d["student_fee"]["fee_structure_name"] = (
            sf.fee_structure.name if sf.fee_structure else None
        )
        d["student_fee"]["academic_year"] = (
            sf.fee_structure.academic_year.name
            if sf.fee_structure and sf.fee_structure.academic_year
            else None
        )
    return d


def _resolve_student_context(student_id: Optional[str]) -> dict:
    """Resolve class name, section, GR number for a student."""
    result = {"class_name": "—", "section": "—", "gr_number": "—", "admission_number": "—"}
    if not student_id:
        return result
    try:
        from modules.students.models import Student
        from modules.classes.models import Class
        student = Student.query.filter_by(id=student_id).first()
        if student:
            result["admission_number"] = student.admission_number or "—"
            result["gr_number"] = student.admission_number or "—"
            if student.class_id:
                cls = Class.query.filter_by(id=student.class_id).first()
                if cls:
                    result["class_name"] = cls.name or "—"
                    result["section"] = cls.section or "—"
    except Exception:
        pass
    return result


def _fmt(amount) -> str:
    """Format a numeric amount with comma-separated thousands."""
    try:
        v = float(amount)
        if v == int(v):
            return f"{int(v):,}"
        return f"{v:,.2f}"
    except (TypeError, ValueError):
        return "0"


def _payment_method_display(method: Optional[str], method_detail: Optional[str] = None) -> str:
    """Human-readable payment method for PDF/HTML (canonical `method` + optional other detail)."""
    if not method:
        return "—"
    labels = {
        "cash": "Cash",
        "upi": "UPI",
        "bank_transfer": "Bank transfer",
        "cheque": "Cheque",
        "other": "Other",
        "online": "Online",
    }
    base = labels.get(method, method.replace("_", " ").title())
    if method == "other" and method_detail:
        return f"{base} — {method_detail}"
    return base


# ---------------------------------------------------------------------------
# Receipt data preparation
# ---------------------------------------------------------------------------

def _build_receipt_context(payment_id: str, show_note: bool = True) -> Optional[dict]:
    data = _get_payment_with_student_fee(payment_id)
    if not data:
        return None

    school = _get_tenant_info()
    sf = data.get("student_fee") or {}
    student_id = sf.get("student_id") or data.get("student_id")
    student_ctx = _resolve_student_context(student_id)

    amount = float(data.get("amount") or 0)
    total = float(sf.get("total_amount") or 0)
    paid = float(sf.get("paid_amount") or 0)
    balance = total - paid

    payment_date = data.get("created_at", "")[:10] if data.get("created_at") else "—"

    items = []
    for it in sf.get("items") or []:
        amt = float(it.get("amount") or 0)
        items.append({
            "fee_head": it.get("component_name") or "—",
            "amount": _fmt(amt),
        })

    return {
        **school,
        "receipt_number": f"RCP-{payment_id[:8].upper()}",
        "payment_date": payment_date,
        "gr_number": student_ctx["gr_number"],
        "student_name": sf.get("student_name") or "—",
        "standard": student_ctx["class_name"],
        "division": student_ctx["section"],
        "academic_year": sf.get("academic_year") or "—",
        "fee_structure_name": sf.get("fee_structure_name") or "—",
        "payment_method": _payment_method_display(
            data.get("method"),
            data.get("method_detail"),
        ),
        "payment_reference": data.get("reference_number") or "—",
        "notes": data.get("notes") or "",
        "old_balance": _fmt(0),
        "items": items,
        "total_amount": _fmt(total),
        "amount_paid": _fmt(amount),
        "balance_amount": _fmt(balance),
        "show_note": show_note,
        "now": datetime.utcnow().strftime("%d-%m-%Y %H:%M UTC"),
    }


# ---------------------------------------------------------------------------
# Invoice data preparation
# ---------------------------------------------------------------------------

def _build_invoice_context(student_fee_id: str, show_note: bool = True) -> Optional[dict]:
    data = get_student_fee(student_fee_id)
    if not data:
        return None

    school = _get_tenant_info()
    student_ctx = _resolve_student_context(data.get("student_id"))

    items = []
    for it in data.get("items") or []:
        amt = float(it.get("amount") or 0)
        paid = float(it.get("paid_amount") or 0)
        items.append({
            "fee_head": it.get("component_name") or "—",
            "amount": amt,
            "paid_amount": paid,
            "outstanding": amt - paid,
        })

    payments = []
    for p in data.get("payments") or []:
        if p.get("status") == "refunded":
            continue
        created = p.get("created_at", "")
        payments.append({
            "date": created[:10] if isinstance(created, str) and len(created) >= 10 else "—",
            "reference": p.get("reference_number") or "—",
            "method": _payment_method_display(p.get("method"), p.get("method_detail")),
            "amount": float(p.get("amount") or 0),
        })

    total = float(data.get("total_amount") or 0)
    paid_total = float(data.get("paid_amount") or 0)

    issue_date = data.get("created_at", "")[:10] if data.get("created_at") else "—"
    due_date = data.get("due_date") or "—"

    return {
        **school,
        "invoice_number": f"INV-{student_fee_id[:8].upper()}",
        "issue_date": issue_date,
        "due_date": due_date,
        "gr_number": student_ctx["gr_number"],
        "student_name": data.get("student_name") or "—",
        "standard": student_ctx["class_name"],
        "division": student_ctx["section"],
        "admission_number": student_ctx["admission_number"],
        "fee_structure_name": data.get("fee_structure_name") or "—",
        "status": (data.get("status") or "").upper(),
        "items": items,
        "payments": payments,
        "total_amount": total,
        "paid_amount": paid_total,
        "outstanding": total - paid_total,
        "show_note": show_note,
        "now": datetime.utcnow().strftime("%d-%m-%Y %H:%M UTC"),
        "_fmt": _fmt,
    }


# ---------------------------------------------------------------------------
# Public render functions
# ---------------------------------------------------------------------------

def _render_receipt_html(payment_id: str, show_note: bool = True, for_print: bool = False) -> Optional[str]:
    ctx = _build_receipt_context(payment_id, show_note=show_note)
    if not ctx:
        return None
    # Use index.html-style templates (finance/receipt_pdf.html, finance/receipt_print.html)
    template_name = "finance/receipt_print.html" if for_print else "finance/receipt_pdf.html"
    return render_template(template_name, **ctx)


def _render_invoice_html(student_fee_id: str, show_note: bool = True, for_print: bool = False) -> Optional[str]:
    ctx = _build_invoice_context(student_fee_id, show_note=show_note)
    if not ctx:
        return None
    template = _INVOICE_PRINT_TEMPLATE if for_print else _INVOICE_PDF_TEMPLATE
    return render_template_string(template, **ctx)


def generate_student_fee_invoice_pdf(student_fee_id: str) -> Optional[bytes]:
    """Generate invoice PDF bytes (with auto-generated note). Returns None on failure."""
    html = _render_invoice_html(student_fee_id, show_note=True, for_print=False)
    if not html:
        return None
    return _html_to_pdf(html)


def generate_finance_receipt_pdf(payment_id: str) -> Optional[bytes]:
    """Generate receipt PDF bytes (with auto-generated note). Returns None on failure."""
    html = _render_receipt_html(payment_id, show_note=True, for_print=False)
    if not html:
        return None
    return _html_to_pdf(html)


def render_student_fee_invoice_html_for_print(student_fee_id: str) -> Optional[str]:
    """Render invoice HTML for browser print (dual-copy, no auto-generated note)."""
    return _render_invoice_html(student_fee_id, show_note=False, for_print=True)


def render_finance_receipt_html_for_print(payment_id: str) -> Optional[str]:
    """Render receipt HTML for browser print (dual-copy, no auto-generated note)."""
    return _render_receipt_html(payment_id, show_note=False, for_print=True)


# ---------------------------------------------------------------------------
# Shared base CSS (kept conservative for printable fee documents)
# Note: legacy quirk — width= on <td> is explicit for older templates.
#       Use <b>, <u>, <i> HTML tags instead of CSS font/decoration classes.
#       Avoid: flexbox, grid, float, white-space:nowrap, text-transform,
#              letter-spacing, nth-child selectors.
# ---------------------------------------------------------------------------

_BASE_STYLES = """
body {
  font-family: Arial, sans-serif;
  font-size: 11px;
  color: #1a1a1a;
  margin: 0;
  padding: 0;
}
table { border-collapse: collapse; }

/* Fee items table */
.fee-th {
  background: #1a1a1a;
  color: #ffffff;
  padding: 6px 8px;
  text-align: left;
  font-size: 10px;
  font-weight: bold;
}
.fee-td {
  padding: 6px 8px;
  border-bottom: 1px solid #dddddd;
}
.fee-td-alt {
  padding: 6px 8px;
  border-bottom: 1px solid #dddddd;
  background: #f8f8f8;
}

/* Separator for print dual-copy */
.cut-line {
  border-top: 2px dashed #555555;
  margin: 14px 0;
  font-size: 9px;
  color: #555555;
  text-align: center;
}
.generated-note {
  text-align: center;
  font-size: 9px;
  color: #888888;
  margin-top: 8px;
  border-top: 1px solid #dddddd;
  padding-top: 4px;
}
"""

# ---------------------------------------------------------------------------
# Invoice single-copy block (Jinja2 macro, HTML-attribute widths only)
# ---------------------------------------------------------------------------

_INVOICE_BLOCK = """
{% macro invoice_copy(copy_label='') %}

{% if copy_label %}
<table width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:5px;">
<tr><td>
  <table cellspacing="0" cellpadding="3"
         style="border:1px solid #aaaaaa;background:#f5f5f5;">
  <tr><td><b style="font-size:9px;">{{ copy_label }}</b></td></tr>
  </table>
</td></tr>
</table>
{% endif %}

{# ── Header ── #}
<table width="100%" cellspacing="0" cellpadding="4" style="margin-bottom:6px;">
<tr>
  <td width="70" valign="middle">
    {% if school_logo %}
    <img src="{{ school_logo }}" width="60" height="60" alt="Logo" />
    {% else %}
    <table width="60" cellspacing="0" cellpadding="0"
           style="border:2px solid #cccccc;background:#f0f0f0;height:60px;">
    <tr><td align="center" valign="middle"
            style="font-size:9px;color:#888888;">LOGO</td></tr>
    </table>
    {% endif %}
  </td>
  <td valign="middle" align="center">
    <b style="font-size:17px;">{{ school_name }}</b>
    {% if school_tagline %}<br/><i style="font-size:10px;">{{ school_tagline }}</i>{% endif %}
    {% if board_affiliation %}<br/><span style="font-size:10px;">{{ board_affiliation }}</span>{% endif %}
    {% if school_address %}<br/><span style="font-size:10px;">{{ school_address }}</span>{% endif %}
    {% if school_phone %}<br/><span style="font-size:10px;">Phone No. : {{ school_phone }}</span>{% endif %}
  </td>
  <td width="90" valign="middle" align="right">
    <table cellspacing="0" cellpadding="6"
           style="border:2px solid #1a1a1a;">
    <tr><td align="center"><b style="font-size:13px;">INVOICE</b></td></tr>
    </table>
  </td>
</tr>
</table>

{# ── Info block ── #}
<table width="100%" cellspacing="0" cellpadding="5"
       style="border:1px solid #888888;margin-top:4px;">
<tr>
  <td width="40%" style="border:1px solid #888888;">
    <b>Invoice No.:</b> {{ invoice_number }}
  </td>
  <td width="30%" style="border:1px solid #888888;">
    <b>Issue Date:</b> {{ issue_date }}
  </td>
  <td width="30%" style="border:1px solid #888888;">
    <b>Due Date:</b> {{ due_date }}
  </td>
</tr>
<tr>
  <td colspan="3" style="border:1px solid #888888;">
    Name : <u><b>{{ student_name }}</b></u>
  </td>
</tr>
<tr>
  <td width="40%" style="border:1px solid #888888;">
    <b>Std. :</b> {{ standard }}
  </td>
  <td width="30%" style="border:1px solid #888888;">
    <b>Div. :</b> {{ division }}
  </td>
  <td width="30%" style="border:1px solid #888888;">
    <b>GR No.:</b> {{ gr_number }}
  </td>
</tr>
<tr>
  <td colspan="2" style="border:1px solid #888888;">
    <b>Fee Structure :</b> {{ fee_structure_name }}
  </td>
  <td width="30%" style="border:1px solid #888888;">
    <b>Status:</b> {{ status }}
  </td>
</tr>
</table>

{# ── Fee items ── #}
<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px;">
<tr>
  <td width="5%"  class="fee-th" align="center">#</td>
  <td width="43%" class="fee-th">Fee Head</td>
  <td width="18%" class="fee-th" align="right">Amount</td>
  <td width="17%" class="fee-th" align="right">Paid</td>
  <td width="17%" class="fee-th" align="right">Outstanding</td>
</tr>
{% for it in items %}
<tr>
  {% if loop.index is odd %}
  <td align="center" class="fee-td">{{ loop.index }}</td>
  <td class="fee-td">{{ it.fee_head }}</td>
  <td align="right" class="fee-td">Rs.{{ "%.0f"|format(it.amount) }}</td>
  <td align="right" class="fee-td">Rs.{{ "%.0f"|format(it.paid_amount) }}</td>
  <td align="right" class="fee-td">Rs.{{ "%.0f"|format(it.outstanding) }}</td>
  {% else %}
  <td align="center" class="fee-td-alt">{{ loop.index }}</td>
  <td class="fee-td-alt">{{ it.fee_head }}</td>
  <td align="right" class="fee-td-alt">Rs.{{ "%.0f"|format(it.amount) }}</td>
  <td align="right" class="fee-td-alt">Rs.{{ "%.0f"|format(it.paid_amount) }}</td>
  <td align="right" class="fee-td-alt">Rs.{{ "%.0f"|format(it.outstanding) }}</td>
  {% endif %}
</tr>
{% else %}
<tr>
  <td colspan="5" align="center" class="fee-td"
      style="color:#888888;padding:10px;">No fee components</td>
</tr>
{% endfor %}
</table>

{# ── Totals ── #}
<table cellspacing="0" cellpadding="5"
       style="width:320px;margin-left:auto;margin-top:8px;
              border:1px solid #cccccc;">
<tr>
  <td width="200" style="border:1px solid #cccccc;background:#f5f5f5;">
    <b>Total Amount</b>
  </td>
  <td align="right" style="border:1px solid #cccccc;background:#f5f5f5;">
    Rs.{{ "%.0f"|format(total_amount) }}
  </td>
</tr>
<tr>
  <td style="border:1px solid #cccccc;background:#f5f5f5;">
    <b>Amount Paid</b>
  </td>
  <td align="right" style="border:1px solid #cccccc;background:#f5f5f5;">
    Rs.{{ "%.0f"|format(paid_amount) }}
  </td>
</tr>
<tr>
  <td style="border:1px solid #cccccc;background:#fff7ed;">
    <b>Remaining Balance</b>
  </td>
  <td align="right"
      style="border:1px solid #cccccc;background:#fff7ed;color:#b45309;">
    <b>Rs.{{ "%.0f"|format(outstanding) }}</b>
  </td>
</tr>
</table>

{# ── Payment history ── #}
{% if payments %}
<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:10px;">
<tr>
  <td width="22%" class="fee-th">Date</td>
  <td width="34%" class="fee-th">Reference</td>
  <td width="18%" class="fee-th">Method</td>
  <td width="26%" class="fee-th" align="right">Amount</td>
</tr>
{% for p in payments %}
<tr>
  {% if loop.index is odd %}
  <td class="fee-td">{{ p.date }}</td>
  <td class="fee-td">{{ p.reference }}</td>
  <td class="fee-td">{{ p.method }}</td>
  <td align="right" class="fee-td">Rs.{{ "%.0f"|format(p.amount) }}</td>
  {% else %}
  <td class="fee-td-alt">{{ p.date }}</td>
  <td class="fee-td-alt">{{ p.reference }}</td>
  <td class="fee-td-alt">{{ p.method }}</td>
  <td align="right" class="fee-td-alt">Rs.{{ "%.0f"|format(p.amount) }}</td>
  {% endif %}
</tr>
{% endfor %}
</table>
{% endif %}

{# ── Signatures ── #}
<table width="100%" cellspacing="0" cellpadding="4"
       style="margin-top:24px;">
<tr>
  <td width="45%" align="center"
      style="border-bottom:1px solid #555555;">
    &nbsp;
  </td>
  <td width="10%"></td>
  <td width="45%" align="center"
      style="border-bottom:1px solid #555555;">
    &nbsp;
  </td>
</tr>
<tr>
  <td align="center" style="font-size:10px;">Parent / Guardian</td>
  <td></td>
  <td align="center" style="font-size:10px;">Authorized Signatory</td>
</tr>
</table>

{# ── Footer disclaimer ── #}
<table width="100%" cellspacing="0" cellpadding="4"
       style="border-top:1px solid #888888;margin-top:8px;">
<tr>
  <td style="font-size:10px;color:#444444;">
    Fees/Amount once paid will not be refundable or transferable.
  </td>
</tr>
</table>

{% if show_note %}
<div class="generated-note">
  This is a system-generated invoice. Generated on {{ now }} | School ERP Finance Module
</div>
{% endif %}

{% endmacro %}
"""

# ---------------------------------------------------------------------------
# Invoice PDF template
# ---------------------------------------------------------------------------

_INVOICE_PDF_TEMPLATE = (
    """<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
@page { size: A4; margin: 14mm 16mm; }
"""
    + _BASE_STYLES
    + """
</style>
</head>
<body>
"""
    + _INVOICE_BLOCK
    + """
{{ invoice_copy() }}
</body>
</html>"""
)

# ---------------------------------------------------------------------------
# Invoice print template (dual copy: office + student)
# ---------------------------------------------------------------------------

_INVOICE_PRINT_TEMPLATE = (
    """<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
@page { size: A4; margin: 8mm 12mm; }
"""
    + _BASE_STYLES
    + """
@media print { .no-print { display: none !important; } }
</style>
</head>
<body>
"""
    + _INVOICE_BLOCK
    + """
{{ invoice_copy(copy_label='OFFICE COPY') }}
<div class="cut-line">&#9988; &nbsp; cut here &nbsp; &#9988;</div>
{{ invoice_copy(copy_label='STUDENT / PARENT COPY') }}
<div class="no-print" style="text-align:center;margin-top:16px;">
  <button onclick="window.print()"
          style="padding:8px 24px;font-size:14px;cursor:pointer;">
    Print
  </button>
</div>
<script>
  if (window.location.search.indexOf('autoprint=1') >= 0) {
    window.onload = function() { window.print(); };
  }
</script>
</body>
</html>"""
)
