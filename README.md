# drp ![version](https://img.shields.io/github/v/tag/vicnasdev/drp)

Drop files or paste text, get a link instantly.  
**[Live →](https://drp.vicnas.me)**
```bash
pipx install drp-cli
drp setup && drp up "hello world"
```

## Deploy

> ⚠️ Self-hosting for personal or internal use only — see [LICENSE](LICENSE).

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.com?referralCode=ZIdvo-)

1. Fork → Railway → connect repo → add PostgreSQL
2. Set env vars (see below)
3. Start command:
```
   python manage.py collectstatic --noinput && python manage.py migrate && gunicorn project.wsgi --bind 0.0.0.0:$PORT --workers 17 --worker-class gthread --threads 2
```
4. Create superuser via Railway shell: `python manage.py createsuperuser`

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✓ | Django secret key |
| `DOMAIN` | ✓ | e.g. `hello.me` |
| `DB_URL` | ✓ | PostgreSQL connection string (Railway injects this) |
| `B2_KEY_ID` | ✓ | Backblaze B2 application key ID |
| `B2_APP_KEY` | ✓ | Backblaze B2 application key secret |
| `B2_BUCKET_NAME` | ✓ | e.g. `drp-files` |
| `B2_ENDPOINT_URL` | ✓ | e.g. `https://s3.us-east-005.backblazeb2.com` |
| `ADMIN_EMAIL` | — | Shown on error pages |
| `RESEND_API_KEY` | — | Transactional email via Resend |
| `DEFAULT_FROM_EMAIL` | — | Defaults to `noreply@{DOMAIN}` |
| `LEMONSQUEEZY_API_KEY` | — | Billing via Lemon Squeezy |
| `LEMONSQUEEZY_SIGNING_SECRET` | — | Webhook signature verification |
| `LEMONSQUEEZY_STORE_ID` | — | Lemon Squeezy store ID |
| `LEMONSQUEEZY_STARTER_VARIANT_ID` | — | Starter plan variant ID |
| `LEMONSQUEEZY_PRO_VARIANT_ID` | — | Pro plan variant ID |
| `ADSENSE_CLIENT` | — | e.g. `ca-pub-xxxxxxxxxxxxxxxx` — enables AdSense |
| `ADSENSE_SLOT` | — | AdSense slot ID |
| `DEBUG` | — | `True` only for local dev, never in production |

## Run locally
```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Set env vars in your shell or a `.env` file:
```bash
SECRET_KEY=any-random-string
DEBUG=True
# B2 vars required for file uploads/downloads
B2_KEY_ID=...
B2_APP_KEY=...
B2_BUCKET_NAME=drp-files
B2_ENDPOINT_URL=https://s3.us-east-005.backblazeb2.com
```

## License

Server: source-available, personal/internal use only.  
See [LICENSE](LICENSE).  
CLI (`cli/`): MIT.