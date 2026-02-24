"""
Commercial license — form + PDF generation.

Flow:
  1. User buys on Lemon Squeezy → LS generates license key.
  2. LS webhook (license_key_created) stores the key in CommercialLicense.
  3. User visits /licensing/ → fills in name + license key.
  4. Server validates key, generates PDF of the signed agreement, returns download.
"""

import io
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from billing.models import CommercialLicense

import logging
logger = logging.getLogger(__name__)


# ── Landing page ──────────────────────────────────────────────────────────────

def licensing_page(request):
    """Show the commercial license info + form."""
    checkout_url = getattr(settings, "LEMONSQUEEZY_COMMERCIAL_URL", "")
    return render(request, "licensing/index.html", {"checkout_url": checkout_url})


# ── Generate PDF ──────────────────────────────────────────────────────────────

@require_POST
def licensing_generate(request):
    """
    Validate the license key and licensee name, then return a PDF download.
    """
    license_key   = (request.POST.get("license_key") or "").strip()
    licensee_name = (request.POST.get("licensee_name") or "").strip()

    if not license_key or not licensee_name:
        return render(request, "licensing/index.html", {
            "error": "Please fill in both your name and license key.",
            "checkout_url": getattr(settings, "LEMONSQUEEZY_COMMERCIAL_URL", ""),
            "form_name": licensee_name,
            "form_key": license_key,
        })

    try:
        lic = CommercialLicense.objects.get(license_key=license_key, is_active=True)
    except CommercialLicense.DoesNotExist:
        return render(request, "licensing/index.html", {
            "error": "License key not found or inactive. Please check your key and try again.",
            "checkout_url": getattr(settings, "LEMONSQUEEZY_COMMERCIAL_URL", ""),
            "form_name": licensee_name,
            "form_key": license_key,
        })

    # Update licensee name on first download (or allow updating)
    if not lic.licensee_name:
        lic.licensee_name = licensee_name
    lic.pdf_downloaded = True
    lic.save(update_fields=["licensee_name", "pdf_downloaded"])

    # Generate PDF
    pdf_bytes = _build_license_pdf(lic, licensee_name)

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="drp-commercial-license-{lic.license_key[:8]}.pdf"'
    return response


# ── PDF builder ───────────────────────────────────────────────────────────────

def _build_license_pdf(lic: CommercialLicense, licensee_name: str) -> bytes:
    """Build a professional PDF of the commercial license agreement."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=1 * inch, rightMargin=1 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "LicTitle", parent=styles["Title"],
        fontSize=22, spaceAfter=4, textColor=HexColor("#111111"),
    )
    subtitle_style = ParagraphStyle(
        "LicSubtitle", parent=styles["Normal"],
        fontSize=11, alignment=TA_CENTER, textColor=HexColor("#666666"),
        spaceAfter=20,
    )
    heading_style = ParagraphStyle(
        "LicHeading", parent=styles["Heading2"],
        fontSize=13, spaceBefore=16, spaceAfter=6,
        textColor=HexColor("#222222"),
    )
    body_style = ParagraphStyle(
        "LicBody", parent=styles["Normal"],
        fontSize=10, leading=14, spaceAfter=6,
        textColor=HexColor("#333333"),
    )
    bullet_style = ParagraphStyle(
        "LicBullet", parent=body_style,
        leftIndent=20, bulletIndent=10,
    )
    detail_style = ParagraphStyle(
        "LicDetail", parent=body_style,
        fontSize=10, leading=14,
    )
    footer_style = ParagraphStyle(
        "LicFooter", parent=styles["Normal"],
        fontSize=8, textColor=HexColor("#999999"), alignment=TA_CENTER,
    )

    # Build content
    story = []

    # Header
    story.append(Paragraph("drp", ParagraphStyle(
        "LogoStyle", parent=styles["Title"],
        fontSize=36, alignment=TA_CENTER, textColor=HexColor("#7c3aed"),
        spaceAfter=2,
    )))
    story.append(Paragraph("Commercial Self-Hosted License", title_style))
    story.append(Paragraph("drp.fyi — clipboard &amp; file sharing", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor("#e5e7eb")))
    story.append(Spacer(1, 12))

    # License details table
    effective_date = lic.issued_at.strftime("%B %d, %Y") if lic.issued_at else timezone.now().strftime("%B %d, %Y")
    expires_str = lic.expires_at.strftime("%B %d, %Y") if lic.expires_at else "One year from effective date"

    details_data = [
        ["Licensee:", licensee_name],
        ["License Key:", lic.license_key],
        ["Effective Date:", effective_date],
        ["Expires:", expires_str],
        ["Governing Jurisdiction:", "Quebec, Canada"],
    ]
    detail_table = Table(details_data, colWidths=[1.8 * inch, 4.5 * inch])
    detail_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TEXTCOLOR", (0, 0), (-1, -1), HexColor("#333333")),
    ]))
    story.append(detail_table)
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor("#e5e7eb")))
    story.append(Spacer(1, 8))

    # License body — each section
    sections = _get_license_sections()
    for heading, paragraphs in sections:
        story.append(Paragraph(heading, heading_style))
        for para in paragraphs:
            if para.startswith("- "):
                story.append(Paragraph(f"• {_escape(para[2:])}", bullet_style))
            elif para.startswith("**") and para.endswith("**"):
                story.append(Paragraph(f"<b>{_escape(para[2:-2])}</b>", body_style))
            elif ":**" in para:
                # Bold label: value
                parts = para.split(":**", 1)
                label = parts[0].lstrip("*")
                value = parts[1].rstrip("*") if len(parts) > 1 else ""
                story.append(Paragraph(f"<b>{_escape(label)}:</b>{_escape(value)}", body_style))
            else:
                story.append(Paragraph(_escape(para), body_style))

    # Footer
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor("#e5e7eb")))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "This document was generated by drp.fyi and constitutes the full license agreement. "
        "For questions: licensing@drp.fyi",
        footer_style,
    ))
    story.append(Paragraph(
        f"Generated on {timezone.now().strftime('%B %d, %Y at %H:%M UTC')}",
        footer_style,
    ))

    doc.build(story)
    return buf.getvalue()


def _escape(text: str) -> str:
    """Escape HTML special chars for reportlab Paragraph."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _get_license_sections():
    """Return the commercial license as structured sections."""
    return [
        ("1. Grant of License", [
            "Licensor grants Licensee a non-exclusive, non-transferable license to:",
            "- Deploy and operate one (1) instance of the drp software on Licensee's own infrastructure",
            "- Modify the source code for internal business purposes",
            "- Use drp to provide file sharing and text storage services to end users",
            "**License Type:** Self-Hosted Deployment (single instance)",
        ]),
        ("2. Permitted Use", [
            "Licensee may:",
            "- Host drp on their own servers or cloud infrastructure",
            "- Store, process, and manage files through drp for business purposes",
            "- Modify the codebase to fit internal requirements",
            "- Create integrations with internal systems",
            "- Access all source code and documentation",
            "**Prohibited Uses:**",
            "- Licensing, reselling, or repackaging drp as a commercial service to third parties",
            "- Operating multiple concurrent instances without separate licenses",
            "- Removing or obscuring copyright notices or license terms",
            "- Sublicensing, renting, or leasing the software",
            "- Reverse-engineering or attempting to extract non-public features for competing products",
            "- Using drp to develop, market, or operate a competing file-sharing or drop service",
        ]),
        ("3. Commercial Use Terms", [
            "**Annual License Fee:** CAD $299/year",
            "**Billing & Renewal:**",
            "- License renews automatically on the anniversary date",
            "- Licensee may cancel with 30 days' written notice before renewal",
            "- Payment processed through Lemon Squeezy",
            "- All fees in CAD (or local currency equivalent)",
            "**No Active Use Requirement:** Licensee may deploy and maintain drp indefinitely as long as the annual license remains active, regardless of usage volume.",
        ]),
        ("4. Ownership & Intellectual Property", [
            "- Licensor retains all ownership of the drp codebase, documentation, and intellectual property",
            "- Licensee owns modifications made for internal use only",
            "- Any contributions or improvements must be offered to Licensor for potential integration (not required)",
            "- Licensor may use feedback and usage data to improve the software",
        ]),
        ("5. Support & Updates", [
            "**Included Support:**",
            "- Access to public GitHub documentation",
            "- Bug reports accepted via GitHub Issues",
            "- Security updates (within 30 days of release)",
            "**Not Included:**",
            "- Priority support or service level agreements (SLAs)",
            "- Customization or development work",
            "- Guaranteed response times",
            "- Phone or direct email support",
        ]),
        ("6. Term & Termination", [
            "**License Term:** One (1) year from purchase date, renewable annually.",
            "**Termination by Licensor:** License terminates immediately if:",
            "- Licensee violates terms of this Agreement and does not cure within 30 days of written notice",
            "- Licensee uses drp in a way that creates legal liability for Licensor",
            "- Payment is more than 30 days overdue",
            "**Termination by Licensee:** Licensee may cancel anytime with 30 days' written notice.",
            "**Upon Expiration:**",
            "- Licensee must cease commercial use of drp",
            "- Licensee may retain data and continue operating with the last licensed version for 30 days (read-only)",
            "- All rights granted under this license terminate",
        ]),
        ("7. Warranties & Disclaimers", [
            "drp is provided \"AS IS\" without warranties of any kind. "
            "Licensor makes no warranty that drp will meet Licensee's specific needs, "
            "be error-free, or uninterrupted. Security and reliability depend on Licensee's "
            "infrastructure and configuration.",
            "**Limitation of Liability:**",
            "- Licensor is not liable for data loss, corruption, or unavailability",
            "- Licensor is not liable for indirect, incidental, or consequential damages",
            "- Licensor's total liability is limited to the annual license fee paid",
            "- Licensee is solely responsible for data backups and disaster recovery",
            "**Data Security:**",
            "- Licensee is responsible for all security, encryption, and compliance matters on their infrastructure",
            "- Licensor is not responsible for data breaches, unauthorized access, or compliance violations",
            "- Licensee must comply with applicable data protection laws (GDPR, CCPA, etc.)",
        ]),
        ("8. Compliance & Regulations", [
            "Licensee agrees to:",
            "- Comply with all applicable laws and regulations in their jurisdiction",
            "- Ensure drp is used only for lawful purposes",
            "- Not use drp to store, transmit, or process illegal content",
            "- Maintain sole responsibility for regulatory compliance (GDPR, HIPAA, etc.)",
            "- Not use drp for purposes that violate third-party rights",
        ]),
        ("9. Confidentiality", [
            "- Licensor may use publicly available information about Licensee's use of drp for case studies or testimonials (unless Licensee opts out)",
            "- Licensee must keep Licensor's proprietary information confidential",
            "- This does not apply to information already in the public domain or independently developed",
        ]),
        ("10. Updates & Changes", [
            "Licensor reserves the right to:",
            "- Update or modify the software",
            "- Change pricing for future renewals (with 60 days' notice)",
            "- Discontinue the software (with 12 months' notice, full refund for unused license period)",
            "- Modify terms of this Agreement (with 30 days' notice; continued use = acceptance)",
        ]),
        ("11. General Provisions", [
            "**Entire Agreement:** This Agreement supersedes all prior agreements regarding drp licensing.",
            "**Severability:** If any provision is found invalid, remaining provisions remain in effect.",
            "**Governing Law:** This Agreement is governed by the laws of Quebec, Canada, without regard to conflicts of law principles.",
            "**Dispute Resolution:** Any disputes shall be resolved through good-faith negotiation; if unresolved after 30 days, either party may pursue legal remedies.",
            "**Contact:** For license inquiries, support issues, or disputes, contact: licensing@drp.fyi",
        ]),
    ]
