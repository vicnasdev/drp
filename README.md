# drp ![version](https://img.shields.io/github/v/tag/vicnasdev/drp)

Drop files or paste text, get a link instantly.  
**[Live →](https://drp.vicnas.me)**

```bash
pipx install drp-cli
drp setup && drp up "hello world"
```

## Deploy

> ⚠️ Self-hosting for personal or internal use only — see [LICENSE](https://github.com/vicnasdev/drp/blob/main/LICENSE).

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.com?referralCode=ZIdvo-)

1. Fork → Railway → connect repo → add PostgreSQL
2. Set env vars (see below)
3. Start command: `python manage.py collectstatic --noinput && python manage.py migrate && gunicorn project.wsgi --bind 0.0.0.0:$PORT`
4. Create superuser via Railway shell: `python manage.py createsuperuser`

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✓ | Django secret key |
| `DOMAIN` | ✓ | e.g. `hello.me` |
| `DB_URL` | ✓ | PostgreSQL connection string |
| `B2_KEY_ID` | ✓ | Backblaze B2 key ID |
| `B2_APP_KEY` | ✓ | Backblaze B2 key secret |
| `B2_BUCKET_NAME` | ✓ | e.g. `drp-files` |
| `B2_ENDPOINT_URL` | ✓ | e.g. `https://s3.us-east-005.backblazeb2.com` |
| `RESEND_API_KEY` | — | Transactional email |
| `LEMONSQUEEZY_API_KEY` | — | Billing |
| `LEMONSQUEEZY_SIGNING_SECRET` | — | Webhook verification |
| `LEMONSQUEEZY_STORE_ID` | — | Store ID |
| `LEMONSQUEEZY_STARTER_VARIANT_ID` | — | Starter plan variant |
| `LEMONSQUEEZY_PRO_VARIANT_ID` | — | Pro plan variant |
| `DEBUG` | — | `True` for local dev only |

## License

Server: source-available, personal/internal use only — see [LICENSE](https://github.com/vicnasdev/drp/blob/main/LICENSE).  
CLI (`cli/`): MIT.