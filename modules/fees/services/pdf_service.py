"""
PDF Service

HTML template → PDF generation using WeasyPrint (see backend README for system libs).
Templates: templates/pdf/fee_invoice.html, templates/pdf/fee_receipt.html
"""

from typing import Optional

from flask import render_template_string
from core.tenant import get_tenant_id

try:
    from weasyprint import HTML
    HAS_WEASYPRINT = True
except (ImportError, OSError):
    HAS_WEASYPRINT = False
    HTML = None  # type: ignore[assignment,misc]


def _html_to_pdf(html: str) -> Optional[bytes]:
    if not HAS_WEASYPRINT or HTML is None:
        return None
    try:
        return HTML(string=html).write_pdf()
    except Exception:
        return None


def _render_invoice_html(invoice_id: str) -> Optional[str]:
    """Render invoice HTML from template."""
    from modules.fees.services.invoice_service import get_invoice
    from datetime import datetime

    tenant_id = get_tenant_id()
    if not tenant_id:
        return None

    data = get_invoice(invoice_id)
    if not data:
        return None

    data["now"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return render_template_string(_INVOICE_TEMPLATE, **data)


def _render_receipt_html(payment_id: str) -> Optional[str]:
    """Render receipt HTML from template."""
    from modules.fees.services.fee_payment_service import get_fee_payment

    data = get_fee_payment(payment_id)
    if not data:
        return None

    return render_template_string(_RECEIPT_TEMPLATE, **data)


def generate_invoice_pdf(invoice_id: str) -> Optional[bytes]:
    """Generate invoice PDF bytes. Returns None on failure."""
    html = _render_invoice_html(invoice_id)
    if not html:
        return None
    return _html_to_pdf(html)


def generate_receipt_pdf(payment_id: str) -> Optional[bytes]:
    """Generate receipt PDF bytes. Returns None on failure."""
    html = _render_receipt_html(payment_id)
    if not html:
        return None
    return _html_to_pdf(html)


# ---------------------------------------------------------------------------
# HTML Templates (inline for simplicity; can be moved to files later)
# ---------------------------------------------------------------------------

_INVOICE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    @page { size: A4; margin: 20mm; }
    body { font-family: DejaVu Sans, sans-serif; font-size: 11px; line-height: 1.4; }
    .header { text-align: center; margin-bottom: 20px; border-bottom: 2px solid #333; padding-bottom: 10px; }
    .school { font-size: 18px; font-weight: bold; }
    .subtitle { font-size: 12px; color: #555; }
    h2 { font-size: 14px; margin: 15px 0 10px; }
    table { width: 100%; border-collapse: collapse; margin: 10px 0; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
    th { background: #f5f5f5; font-weight: bold; }
    .text-right { text-align: right; }
    .totals { margin-top: 15px; }
    .totals table { max-width: 300px; margin-left: auto; }
    .payment-history { margin-top: 20px; }
    .footer { margin-top: 30px; font-size: 10px; color: #666; }
  </style>
</head>
<body>
  <div class="header">
    <div class="school">School ERP - Fee Invoice</div>
    <div class="subtitle">Academic Year: {{ academic_year }}</div>
  </div>

  <h2>Invoice Details</h2>
  <table>
    <tr><th>Invoice Number</th><td>{{ invoice_number }}</td></tr>
    <tr><th>Issue Date</th><td>{{ issue_date }}</td></tr>
    <tr><th>Due Date</th><td>{{ due_date }}</td></tr>
    <tr><th>Student ID</th><td>{{ student_id }}</td></tr>
    <tr><th>Status</th><td>{{ status }}</td></tr>
  </table>

  <h2>Fee Breakdown</h2>
  <table>
    <thead>
      <tr>
        <th>Fee Head</th>
        <th>Period</th>
        <th class="text-right">Amount</th>
        <th class="text-right">Discount</th>
        <th class="text-right">Fine</th>
        <th class="text-right">Net</th>
      </tr>
    </thead>
    <tbody>
      {% for it in items %}
      <tr>
        <td>{{ it.fee_head }}</td>
        <td>{{ it.period or '-' }}</td>
        <td class="text-right">₹{{ "{:.2f}".format(it.amount) }}</td>
        <td class="text-right">₹{{ "{:.2f}".format(it.discount) }}</td>
        <td class="text-right">₹{{ "{:.2f}".format(it.fine) }}</td>
        <td class="text-right">₹{{ "{:.2f}".format(it.net_amount) }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <div class="totals">
    <table>
      <tr><th>Subtotal</th><td class="text-right">₹{{ "{:.2f}".format(subtotal) }}</td></tr>
      <tr><th>Total Discount</th><td class="text-right">- ₹{{ "{:.2f}".format(total_discount) }}</td></tr>
      <tr><th>Total Fine</th><td class="text-right">+ ₹{{ "{:.2f}".format(total_fine) }}</td></tr>
      <tr><th><strong>Total Amount</strong></th><td class="text-right"><strong>₹{{ "{:.2f}".format(total_amount) }}</strong></td></tr>
      <tr><th>Amount Paid</th><td class="text-right">₹{{ "{:.2f}".format(amount_paid) }}</td></tr>
      <tr><th><strong>Remaining Balance</strong></th><td class="text-right"><strong>₹{{ "{:.2f}".format(remaining_balance) }}</strong></td></tr>
    </table>
  </div>

  <h2>Payment History</h2>
  <table class="payment-history">
    <thead>
      <tr>
        <th>Date</th>
        <th>Reference</th>
        <th>Method</th>
        <th class="text-right">Amount</th>
      </tr>
    </thead>
    <tbody>
      {% for p in payments %}
      <tr>
        <td>{{ p.payment_date or p.created_at }}</td>
        <td>{{ p.payment_reference or '-' }}</td>
        <td>{{ p.payment_method }}</td>
        <td class="text-right">₹{{ "{:.2f}".format(p.amount) }}</td>
      </tr>
      {% else %}
      <tr><td colspan="4">No payments yet</td></tr>
      {% endfor %}
    </tbody>
  </table>

  {% if notes %}
  <p><strong>Notes:</strong> {{ notes }}</p>
  {% endif %}

  <div class="footer">
    Generated on {{ now }} | School ERP Fees Module
  </div>
</body>
</html>
"""

_RECEIPT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    @page { size: A4; margin: 20mm; }
    body { font-family: DejaVu Sans, sans-serif; font-size: 11px; line-height: 1.4; }
    .header { text-align: center; margin-bottom: 20px; border-bottom: 2px solid #333; padding-bottom: 10px; }
    .title { font-size: 20px; font-weight: bold; }
    h2 { font-size: 14px; margin: 15px 0 10px; }
    table { width: 100%; border-collapse: collapse; margin: 10px 0; }
    th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
    th { background: #f5f5f5; font-weight: bold; }
    .text-right { text-align: right; }
    .amount-paid { font-size: 18px; color: #0a0; font-weight: bold; margin: 15px 0; }
    .footer { margin-top: 30px; font-size: 10px; color: #666; }
  </style>
</head>
<body>
  <div class="header">
    <div class="title">FEE RECEIPT</div>
    <div>Receipt No: {{ receipt.receipt_number }}</div>
  </div>

  <h2>Payment Details</h2>
  <table>
    <tr><th>Receipt Number</th><td>{{ receipt.receipt_number }}</td></tr>
    <tr><th>Payment Reference</th><td>{{ payment_reference or '-' }}</td></tr>
    <tr><th>Transaction ID</th><td>{{ transaction_id or '-' }}</td></tr>
    <tr><th>Payment Method</th><td>{{ payment_method }}</td></tr>
    <tr><th>Payment Date</th><td>{{ payment_date }}</td></tr>
    <tr><th>Invoice</th><td>{{ invoice.invoice_number if invoice else '-' }}</td></tr>
  </table>

  <div class="amount-paid">Amount Paid: ₹{{ "{:.2f}".format(amount) }}</div>

  {% if invoice and invoice.items %}
  <h2>Fee Breakdown (Invoice)</h2>
  <table>
    <thead>
      <tr>
        <th>Fee Head</th>
        <th class="text-right">Net Amount</th>
      </tr>
    </thead>
    <tbody>
      {% for it in invoice.items %}
      <tr>
        <td>{{ it.fee_head }}</td>
        <td class="text-right">₹{{ "{:.2f}".format(it.net_amount) }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  <div class="footer">
    Thank you for your payment. | School ERP Fees Module
  </div>
</body>
</html>
"""
