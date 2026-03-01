# drp — Architecture Reference

## What it is

drp is a file sharing service. Files are identified by short random keys (`xK9mZ2`) that form URLs (`drp.fyi/xK9mZ2`). The CLI is the primary interface. The web is for viewing and account management.

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `django-insecure-changeme` | Django secret key. |
| `DEBUG` | `False` | Django debug mode. |
| `ENVIRONMENT` | `dev` | `dev` or `prod`. Controls B2 bucket and domain. |
| `DOMAIN` | `drp.fyi` (prod) / `dev.drp.fyi` (dev) | `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL`. |
| `DB_URL` | SQLite | Postgres connection string. |
| `B2_KEY_ID` | — | Backblaze B2 key ID. Required. |
| `B2_APP_KEY` | — | Backblaze B2 key. Required. |
| `B2_BUCKET_NAME` | `drp-files-test` / `drp-files` | B2 bucket. Derived from `ENVIRONMENT`. |
| `B2_ENDPOINT_URL` | `https://s3.us-east-005.backblazeb2.com` | B2 S3-compatible endpoint. |
| `RESEND_API_KEY` | — | Resend API key. Falls back to console if absent. |
| `DEFAULT_FROM_EMAIL` | `noreply@{DOMAIN}` | From address on outbound emails. |
| `LEMONSQUEEZY_API_KEY` | — | Lemon Squeezy API key. |
| `LEMONSQUEEZY_SIGNING_SECRET` | — | Webhook HMAC validation. |
| `LEMONSQUEEZY_STORE_ID` | — | Store ID. |
| `LEMONSQUEEZY_STARTER_VARIANT_ID` | — | Starter plan variant ID. |
| `LEMONSQUEEZY_PRO_VARIANT_ID` | — | Pro plan variant ID. |
| `LEMONSQUEEZY_COMMERCIAL_URL` | — | Commercial license checkout URL. |
| `ADSENSE_CLIENT` | — | Google AdSense publisher ID. Empty disables ads. |
| `ADSENSE_SLOT` | — | AdSense slot ID. |
| `GITHUB_ISSUES_TOKEN` | — | GitHub PAT with `repo` scope for crash issue filing. |
| `GITHUB_REPO` | `vicnasdev/drp` | Target repo for filed issues. |
| `LLM_BASE_URL` | — | OpenAI-compatible endpoint for the help bot. |
| `LLM_MODEL` | `qwen2.5:1.5b` | Model name for the LLM. |
| `CONTACT_DAILY_LIMIT` | `3` | Max contact submissions per user per day. |

---

## Plans

| Plan | Storage | Max file | Max key expiry | Password | Custom keys | Helpbot/hr |
|---|---|---|---|---|---|---|
| anonymous | — | 200 MB | 1 day | no | no | 0 |
| free | 1 GB | 200 MB | 7 days | no | yes | 5 |
| starter | 5 GB | 1 GB | 365 days | yes | yes | 30 |
| pro | 20 GB | 5 GB | 3 years | yes | yes | 120 |

Folders are unlimited on every plan. Path access (browsing `/@user/…`) is a Pro feature.

---

## Accounts

Every visitor gets a real account. Anonymous visitors get a temporary account with a generated username. Sign-up lets them claim the username and add a password. Email verification clears `is_anonymous` and enables email login.

---

## Files, Keys, and Paths

Every file gets a short random **key**. Keys expire, not files. The `expires_at` is on the key record.

**Key URL** (`drp.fyi/xK9mZ2`): always works if the key is valid (not expired, not burned). Prompts for password if set, prompts for encryption passphrase if encrypted.

**Path URL** (`drp.fyi/@user/folder/file.ext`): resolves a file by its filename within the folder tree.
- Owner can always access via path.
- Non-owner access is **forbidden by default** on all plans.
- Pro users can activate path access per-folder. Children inherit. Can re-enable specific sub-folders within a disabled tree.
- Folder passwords gate the listing. File passwords gate the content. Both can apply.
- Encrypted files prompt for passphrase (in-browser JS AES decryption on web, interactive prompt in CLI).

**No duplicate filenames** within the same folder — the drive enforces uniqueness like a filesystem.

Key properties: burn-after-read, custom keys (free+), password protection (starter+), publish (listed on `/explore/`), tags, client-side AES encryption.

---

## Storage

Backblaze B2 via S3 API (boto3). Object names: `{uuid4}/{original_filename}`. Downloads are presigned URLs (1-hour TTL). Server never proxies content.

---

## Web

| Route | Description |
|---|---|
| `/{key}/` | File page. Syntax-highlighted text, inline images, download button. Password/encryption prompt if needed. |
| `/{key}/raw/` | Raw content. |
| `/{key}/download/` | Force download. |
| `/embed/{key}/` | Minimal iframe-embeddable view. |
| `/explore/` | Public files feed. Search, tags, sort by newest/likes. |
| `/@{user}/` | Profile — owner sees everything, visitors see published items. |
| `/@{user}/{path}/` | Folder/file by path. Pro path-access rules apply. |
| `/contact/` | Contact form (bug, feature, question, billing, other). |

Web supports in-browser AES encryption and decryption — same capabilities as CLI.

---

## REST API (`/api/v1/`)

Auth via `Authorization: Bearer <token>` (SHA-256 hashed in DB). Exceptions: `ping`, `auth/login/`, `crash/`.

| Endpoint | Methods | Description |
|---|---|---|
| `ping/` | GET | Health check |
| `auth/login/` | POST | Username + password → token |
| `auth/logout/` | POST | Revoke token |
| `auth/me/` | GET | Account info |
| `files/` | GET, POST | List / upload |
| `files/{key}/` | GET, PATCH, DELETE | File metadata / update / delete |
| `files/{key}/fork/` | POST | Fork into your account |
| `folders/` | GET, POST | List folders / create |
| `folders/{id}/` | GET, PATCH, DELETE | Folder contents / update / delete |
| `resolve/` | GET | Resolve `@user/path` to folder |
| `tokens/` | GET, POST | List / create API tokens |
| `tokens/{id}/` | DELETE | Revoke token |
| `helpbot/` | POST | Help bot Q&A |
| `crash/` | POST | CLI crash reporting |

Upload fields: `file`, `key`, `burn`, `publish`, `expires`, `folder_id`, `password`, `tags` (JSON array).

---

## CLI

Installed as `drp`. Config at `~/.config/drp/config.toml`. `drp` with no args opens the shell.

### Commands

| Command | Description | Shell only |
|---|---|---|
| `up <target>` | Upload file, dir, glob, stdin, or text | |
| `get <key\|url>` | Download a file (key, full URL, or path URL) | |
| `cat <ref>` | Display file with syntax highlighting | |
| `cp <src> <dest>` | Copy between filesystem and drive | ✓ |
| `mv <src> <dest>` | Move/rename within drive | ✓ |
| `rm <ref>` | Delete file or folder | |
| `ls [path]` | List files and folders | |
| `cd <path>` | Change drive directory | ✓ |
| `mkdir <name>` | Create folder | ✓ |
| `edit <file>` | Edit in `$EDITOR`, re-upload if changed | ✓ |
| `fork <key>` | Copy someone else's file to your account | |
| `ask "<q>"` | Help bot | |
| `ping` | Server connectivity check | |
| `status` | Account info | |
| `login` | Authenticate | |
| `logout` | Revoke token | |
| `token` | Manage API tokens (create/list/revoke) | |
| `getkey <file>` | Print key for filename | ✓ |
| `setkey <file> <key>` | Rename a file's key | ✓ |
| `setup` | First-time config wizard | |

Key flags on `up`: `--key`, `--expires`, `--publish`, `--burn`, `--password`, `--encrypt`, `--tag`, `--text`.
Key flags on `get`/`cat`: `--decrypt`, `--stdout`, `--fork`, `--password`.

`get` accepts a bare key (`xK9mZ2`), a full URL (`https://drp.fyi/xK9mZ2/`), or a path URL (`https://drp.fyi/@user/folder/file.ext`). The CLI extracts the key or resolves the path server-side.

---

## Shell

REPL with drive navigation. Prompt: `drp:/@user/path>`. Tab completion for commands, flags, drive files, and local paths (prefixed `./`).

---

## Encryption

`up --encrypt <passphrase>` — client-side AES before upload. Server stores opaque bytes. Decrypt with `--decrypt` on `get` or `cat`. Web does the same in-browser.

---

## Crash Reporting

Every unhandled exception files a GitHub issue on first occurrence. Pipeline: exception → SHA-256 fingerprint → dedup in `CrashReport` table → POST to GitHub Issues API. Subsequent hits increment `hit_count`. CLI crashes POST to `/api/v1/crash/`. Web 500s use the same `maybe_file_issue()` logic.

---

## Billing

Lemon Squeezy webhooks set/clear user plan. HMAC-validated. Cancellation downgrades to free.
