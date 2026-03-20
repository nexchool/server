"""
Fees Module - Invoice, Payment, Receipt system

Industry-grade fee invoice and receipt system with PDF generation and reminders.
Invoices represent fee dues; payments can be partial; each payment generates a receipt.
"""

from flask import Blueprint

fees_bp = Blueprint("fees", __name__, url_prefix="/fees")

from . import routes  # noqa: E402, F401
