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
   python manage.py collectstatic --noinput && python manage.py migrate       
   && gunicorn project.wsgi --bind 0.0.0.0:$PORT
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

## Registration & accounts

Signup requires a **username** (alphanumeric + hyphens, unique, case-insensitive) in addition to email and password. The username becomes the namespace for your public collection URLs: `/@alice/my-notes/`.

Usernames are stored in `auth_User.username`. The email address is used for login and notifications — it is not the username.

## CLI quick reference

```bash
# Setup
drp setup              # configure host, login
drp login / drp logout

# Basic drops
drp up "text"          # upload text to a new key
drp up file.pdf        # upload a file
drp get <key>          # fetch and print text drop
drp get -f <key>       # download file drop
drp rm <key>           # delete a drop
drp cp <key> <new>     # copy a drop
drp mv <key> <new>     # rename a drop

# Listing
drp ls                 # list your drops
drp ls --col           # list your collections instead

# Status
drp status             # show config, session, server + local drop counts
drp status <key>       # show view count and last-viewed for a specific drop

# Collections (Starter and Pro plans)
drp collection ls                    # list your collections
drp collection new "My Notes"        # create a collection (slug auto-generated)
drp collection add <slug> <key>      # add a text drop to a collection
drp collection add <slug> -f <key>   # add a file drop to a collection
drp collection rm <slug> <key>       # remove a drop from a collection
drp collection open <slug>           # print the collection's public URL

# Interactive shell
drp shell              # open a REPL with ls, cat, rm, cp, mv, cd into collections

# Utilities
drp diff <key1> <key2> # diff two text drops
drp serve <dir>        # upload every file in a directory as file drops
drp load backup.json   # import a saved export
```

### drp shell

`drp shell` opens an interactive REPL. Supported commands:

| Command | Description |
|---|---|
| `ls` | list drops |
| `ls --col` | list collections |
| `cat <key>` | print text drop (prompts for password if protected) |
| `rm <key>` | delete a drop |
| `cp <key> <new>` | copy a drop |
| `mv <key> <new>` | rename a drop |
| `cd <slug>` | enter a collection (changes `ls` scope) |
| `cd ..` | exit collection back to root |
| `exit` / `quit` | leave the shell |

Password-protected drops: `cat` will automatically prompt for the password when the server returns 401, then retry. This matches the behaviour of `drp get`.

### Tab completion

```bash
# Bash
eval "$(register-python-argcomplete drp)"

# Zsh
eval "$(register-python-argcomplete drp)"

# Fish
register-python-argcomplete --shell fish drp | source
```

Drop keys and collection slugs complete from a local cache refreshed in the background every 30 seconds.

## Plan limits

Plan limits (max file size, storage quota, collection count, etc.) are stored in the `PlanLimit` database table — not hardcoded in the application. To change a limit:

1. Open Django admin → Plan limits
2. Edit the row for the relevant plan
3. Save — the change takes effect on the next request (no deploy needed)

The in-process cache is invalidated automatically on each admin save.

## License

Server: source-available, personal/internal use only.  
See [LICENSE](LICENSE).  
CLI (`cli/`): MIT.
