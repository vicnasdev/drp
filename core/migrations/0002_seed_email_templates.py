"""Seed default email templates so admin page isn't empty."""

from django.db import migrations


BUG_FIX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Your bug report has been resolved</title>
  <style>
    body {{
      margin: 0; padding: 0;
      background: #0d0d0d;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #e0e0e0;
    }}
    .wrapper {{
      max-width: 560px;
      margin: 40px auto;
      background: #161616;
      border: 1px solid #2a2a2a;
      border-radius: 10px;
      overflow: hidden;
    }}
    .header {{
      background: #1a1a1a;
      border-bottom: 1px solid #2a2a2a;
      padding: 24px 32px;
    }}
    .header .logo {{
      font-size: 1.3rem;
      font-weight: 700;
      letter-spacing: -.5px;
      color: #fff;
    }}
    .body {{
      padding: 32px;
    }}
    .badge {{
      display: inline-block;
      background: #0f2a0f;
      color: #4ade80;
      border: 1px solid #166534;
      border-radius: 999px;
      font-size: .78rem;
      font-weight: 600;
      letter-spacing: .04em;
      padding: .25rem .75rem;
      margin-bottom: 1.2rem;
    }}
    h1 {{
      font-size: 1.35rem;
      font-weight: 700;
      color: #fff;
      margin: 0 0 .6rem;
    }}
    p {{
      font-size: .93rem;
      line-height: 1.6;
      color: #aaa;
      margin: 0 0 1rem;
    }}
    .report-box {{
      background: #111;
      border: 1px solid #2a2a2a;
      border-radius: 6px;
      padding: 14px 18px;
      margin: 1.2rem 0;
    }}
    .report-box .label {{
      font-size: .75rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: .06em;
      color: #555;
      margin-bottom: .35rem;
    }}
    .report-box .value {{
      font-size: .9rem;
      color: #ccc;
    }}
    .btn {{
      display: inline-block;
      background: #fff;
      color: #111;
      font-size: .9rem;
      font-weight: 600;
      text-decoration: none;
      padding: .6rem 1.4rem;
      border-radius: 6px;
      margin: .5rem 0 1.2rem;
    }}
    .footer {{
      border-top: 1px solid #222;
      padding: 20px 32px;
      font-size: .78rem;
      color: #444;
      line-height: 1.6;
    }}
    .footer a {{
      color: #555;
    }}
  </style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <span class="logo">drp</span>
  </div>
  <div class="body">
    <div class="badge">\u2713 Resolved</div>
    <h1>Your bug report has been fixed \U0001f389</h1>
    <p>
      Good news \u2014 the issue you reported has been marked as resolved.
      The fix will be included in this week\u2019s update unless it was flagged as urgent,
      in which case it\u2019s already live.
    </p>
    <div class="report-box">
      <div class="label">Category</div>
      <div class="value">{category_display}</div>
    </div>
    <div class="report-box">
      <div class="label">Your report</div>
      <div class="value">{short_desc}</div>
    </div>
    <p style="margin-top:1.2rem">
      <a href="{issue_url}" class="btn">View issue on GitHub \u2192</a>
    </p>
    <p style="font-size:.85rem;color:#666">
      Thanks for helping make drp better.
    </p>
  </div>
  <div class="footer">
    You received this email because you submitted a bug report on drp
    and bug fix notifications are enabled in your account.<br>
    <a href="{account_url}">Manage notification preferences</a>
  </div>
</div>
</body>
</html>"""

VERIFY_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Verify your email</title>
  <style>
    body {{
      margin: 0; padding: 0;
      background: #0d0d0d;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #e0e0e0;
    }}
    .wrapper {{
      max-width: 560px;
      margin: 40px auto;
      background: #161616;
      border: 1px solid #2a2a2a;
      border-radius: 10px;
      overflow: hidden;
    }}
    .header {{
      background: #1a1a1a;
      border-bottom: 1px solid #2a2a2a;
      padding: 24px 32px;
    }}
    .header .logo {{
      font-size: 1.3rem;
      font-weight: 700;
      letter-spacing: -.5px;
      color: #fff;
    }}
    .body {{
      padding: 32px;
    }}
    h1 {{
      font-size: 1.35rem;
      font-weight: 700;
      color: #fff;
      margin: 0 0 .6rem;
    }}
    p {{
      font-size: .93rem;
      line-height: 1.6;
      color: #aaa;
      margin: 0 0 1rem;
    }}
    .btn {{
      display: inline-block;
      background: #fff;
      color: #111;
      font-size: .9rem;
      font-weight: 600;
      text-decoration: none;
      padding: .6rem 1.4rem;
      border-radius: 6px;
      margin: .5rem 0 1.2rem;
    }}
    .footer {{
      border-top: 1px solid #222;
      padding: 20px 32px;
      font-size: .78rem;
      color: #444;
      line-height: 1.6;
    }}
  </style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <span class="logo">drp</span>
  </div>
  <div class="body">
    <h1>Verify your email address</h1>
    <p>Click the button below to verify your drp email. The link expires in 24 hours.</p>
    <p>
      <a href="{verify_url}" class="btn">Verify email \u2192</a>
    </p>
    <p style="font-size:.82rem;color:#555">
      If you did not create a drp account, ignore this email.
    </p>
  </div>
  <div class="footer">
    \u2014 drp
  </div>
</div>
</body>
</html>"""


TEMPLATES = [
    {
        "slug": "bug_fix_notification",
        "description": "Sent when a user's bug report is resolved via GitHub webhook",
        "subject": "Your bug report has been resolved \U0001f389",
        "body_text": "",
        "body_html": BUG_FIX_HTML,
        "from_email": "",
    },
    {
        "slug": "verify_email",
        "description": "Email verification link sent during signup / re-verify",
        "subject": "Verify your drp email address",
        "body_text": "",
        "body_html": VERIFY_HTML,
        "from_email": "",
    },
]


def seed(apps, schema_editor):
    EmailTemplate = apps.get_model("core", "EmailTemplate")
    for t in TEMPLATES:
        EmailTemplate.objects.update_or_create(
            slug=t["slug"],
            defaults=t,
        )


def unseed(apps, schema_editor):
    EmailTemplate = apps.get_model("core", "EmailTemplate")
    EmailTemplate.objects.filter(slug__in=[t["slug"] for t in TEMPLATES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]
    operations = [
        migrations.RunPython(seed, unseed),
    ]
