# drp — Architecture Reference

## What it is

drp is a file and text sharing service. Everything uploaded is a **file** identified by a short random key (`xK9mZ2`) that forms its URL (`drp.fyi/xK9mZ2`). The CLI is the primary interface. The web frontend is for viewing files and account management.

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | `django-insecure-changeme` | Django secret key. Must be changed in prod. |
| `DEBUG` | `False` | Django debug mode. |
| `ENVIRONMENT` | `dev` | `dev` or `prod`. Controls B2 bucket selection and domain defaults. |
| `DOMAIN` | `drp.fyi` (prod) / `dev.drp.fyi` (dev) | Sets `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL`, and the default from-address for email. |
| `DB_URL` | SQLite | Postgres connection string. Overrides SQLite entirely when set. |
| `B2_KEY_ID` | — | Backblaze B2 application key ID. Required. |
| `B2_APP_KEY` | — | Backblaze B2 application key. Required. |
| `B2_BUCKET_NAME` | `drp-files-test` (dev) / `drp-files` (prod) | B2 bucket. Derived from `ENVIRONMENT` if not set. |
| `B2_ENDPOINT_URL` | `https://s3.us-east-005.backblazeb2.com` | B2 S3-compatible endpoint. |
| `RESEND_API_KEY` | — | Resend API key. If absent, email falls back to console output. |
| `DEFAULT_FROM_EMAIL` | `noreply@{DOMAIN}` | From address on all outbound emails. |
| `LEMONSQUEEZY_API_KEY` | — | Lemon Squeezy API key. Required for billing. |
| `LEMONSQUEEZY_SIGNING_SECRET` | — | Validates incoming Lemon Squeezy webhook payloads. |
| `LEMONSQUEEZY_STORE_ID` | — | Store ID. |
| `LEMONSQUEEZY_STARTER_VARIANT_ID` | — | Product variant ID for the Starter plan. |
| `LEMONSQUEEZY_PRO_VARIANT_ID` | — | Product variant ID for the Pro plan. |
| `LEMONSQUEEZY_COMMERCIAL_URL` | — | Checkout URL for commercial licensing. |
| `ADSENSE_CLIENT` | — | Google AdSense publisher ID. Empty disables ads entirely. |
| `ADSENSE_SLOT` | — | AdSense slot ID. |
| `TURNSTILE_SITE_KEY` | — | Cloudflare Turnstile site key. Currently disabled. |
| `TURNSTILE_SECRET_KEY` | — | Cloudflare Turnstile secret. Currently disabled. |
| `GITHUB_WEBHOOK_SECRET` | — | Validates the HMAC signature on incoming GitHub webhook payloads. Unrelated to issue filing. |
| `GITHUB_ISSUES_TOKEN` | — | GitHub personal access token with `repo` scope. Required for automatic issue filing on unhandled exceptions. If unset, crashes are deduplicated in the DB but no issue is created. |
| `GITHUB_REPO` | `vicnasdev/drp` | Target repo for filed issues. Format: `owner/repo`. |
| `LLM_BASE_URL` | — | OpenAI-compatible endpoint for the help bot (e.g. Ollama). Help bot is disabled if unset. |
| `LLM_MODEL` | `qwen2.5:1.5b` | Model name passed to the LLM. |
| `BUG_REPORT_DAILY_LIMIT` | `3` | Max bug reports a user can submit per calendar day. |
| `ADMIN_EMAIL` | — | Admin contact address. Informational only. |

---

## Plans

| Plan | Storage | Max file | Max key expiry | Folders | Password-protected files | Custom keys | Help bot calls/hr |
|---|---|---|---|---|---|---|---|
| anonymous | — | 200 MB | 1 day | none | no | no | 0 |
| free | 1 GB | 200 MB | 7 days | 3 | no | yes | 5 |
| starter | 5 GB | 1 GB | 365 days | 10 | yes | yes | 30 |
| pro | 20 GB | 5 GB | 3 years | unlimited | yes | yes | 120 |

Plans are stored on the user profile. Limits are enforced at upload time. Billing is handled via Lemon Squeezy webhooks which set the plan field. On a paid plan selection at registration, the user is sent to Lemon Squeezy checkout immediately.

---

## Account Model

Every visitor has a real account. There is no separate "guest session" concept. When someone arrives without signing in, they get a temporary account with a generated username — the sign-up UI lets them claim or change that username and add a password, as though they were never signed in. No file migration needed.

Accounts have an `is_anonymous` flag. While `is_anonymous` is set:
- The account works fully — they can upload, manage files, use the CLI (via username only).
- **Login via email is not possible** — the email address is unverified, so the server does not accept it as a credential. The CLI `login` command only accepts username + password for anonymous accounts.
- Sign-up prompts appear in the UI with their current username pre-filled.

Email verification clears `is_anonymous` and makes the account permanent. It does not gate any feature. Once verified, the user can log in with their email address as well as their username.

---

## Files and Keys

Every uploaded file gets a short random **key** (`xK9mZ2`). The key is the public identifier — the URL, the thing you share, the thing you reference in the CLI.

**Keys expire, not files.** The `expires_at` field is on the key record. When a key expires, the URL stops working and the key is no longer valid. The underlying file content in B2 may be cleaned up separately. The expiry is set at upload time based on the uploading account's plan limits.

Other key properties:
- **Burn after read**: the key is invalidated immediately after the first view.
- **Custom keys**: free plan and above. Format: `[a-zA-Z0-9_\-]{1,64}`. Rejected if already taken.
- **Password protection**: a password hash is stored on the key. The key cannot be accessed without the password. Starter and Pro plans only. A browser session remembers unlocked keys within the same visit.
- **Public**: public keys appear on `/explore/` and the owner's profile.
- **Tags**: a list of strings on the key record. Used for filtering on the explore page.

---

## Storage

All file content goes to Backblaze B2 via the S3-compatible API (boto3, SigV4 signatures). Object names are `{uuid4_hex}/{original_filename}`. The server never proxies content — downloads are B2 presigned URLs with a 1-hour TTL. Two buckets: `drp-files-test` (dev) and `drp-files` (prod).

---

## Web

### File page (`/{key}/`)
Displays the file. Text and code is syntax-highlighted. Images are shown inline. Other types show a download button. Password-protected files show a prompt first. Burn-after-read files invalidate their key after this view.

### Embed (`/embed/{key}/`)
Minimal iframe-embeddable view of a file. No chrome.

### Raw / Download
`/{key}/raw/` — raw content served directly. `/{key}/download/` — forces browser download via `Content-Disposition: attachment`.

### Explore (`/explore/`)
Feed of public files. Filterable by text search and tag. Sortable by newest or most liked.

### Profile (`/@{username}/`)
Owner sees all their folders and loose files. Visitors see only public folders and public files.

### Folder view (`/@{username}/{folder_slug}/`)
Contents of a specific folder.

### Likes
One like per user per file. Tracked by IP for anonymous sessions.

### Bookmarks
Users can save any file by key. The bookmark button is an inline partial updated without a page reload.

### Bug reports (`/report-bug/`)
Logged-in users only. Category + description. Rate-limited to `BUG_REPORT_DAILY_LIMIT` per day. Identity can be hidden.

### Help bot
LLM-backed Q&A. Requires `LLM_BASE_URL`. History stored per user (last 20 exchanges). Rate-limited by plan tier.

---

## REST API (`/api/v1/`)

All endpoints require `Authorization: Bearer <token>` except `ping`, `auth/login/`, and `crash/`. Tokens are SHA-256 hashed in the database. Middleware resolves the token to a user on every request.

| Endpoint | Methods | Description |
|---|---|---|
| `/api/v1/ping/` | GET | Health check |
| `/api/v1/auth/login/` | POST | Username + password → bearer token |
| `/api/v1/auth/logout/` | POST | Revoke current token |
| `/api/v1/auth/me/` | GET | Account info, plan, storage usage |
| `/api/v1/files/` | GET, POST | List owned files / upload |
| `/api/v1/files/{key}/` | GET, PATCH, DELETE | Metadata / update / delete |
| `/api/v1/files/{key}/fork/` | POST | Fork a file into your account |
| `/api/v1/folders/` | GET, POST | List root folders + loose files / create folder |
| `/api/v1/folders/{id}/` | GET, PATCH, DELETE | Folder contents / update / delete |
| `/api/v1/drive/version/` | GET | Drive state hash for cache invalidation |
| `/api/v1/resolve/` | GET | Resolve `@user/folder/subfolder` path to a folder object |
| `/api/v1/tokens/` | GET, POST | List / create API tokens |
| `/api/v1/tokens/{id}/` | DELETE | Revoke a token |
| `/api/v1/helpbot/` | POST | Ask the help bot |
| `/api/v1/crash/` | POST | CLI crash reporting |

**Upload fields** (multipart POST `/api/v1/files/`): `file`, `key`, `burn`, `public`, `expires` (`7d`, `12h`…), `folder_id`, `password`, `tags` (JSON array).

---

## CLI

Installed as `drp`. Config at `~/.config/drp/config.toml`. All commands work standalone. Running `drp` with no arguments opens the interactive shell.

Progress bars use the format:

```
filename.zip  [=======>          ]  2.1 MB / 8.4 MB  3.2 MB/s
```

---

## Shell

The shell is a REPL where the working directory is a path inside your drive. The drive is navigated exactly like a filesystem, with `@username` as the root.

```
drp:/@vicnas> cd projects
drp:/@vicnas/projects> ls
drp:/@vicnas/projects> up ./build.zip
drp:/@vicnas/projects> cd ..
drp:/@vicnas>
```

**`cd @otherusername`** navigates into another user's public drive. You can browse and `get` their public files but not upload or delete.

The shell starts at `/@username/` on every launch. It does not restore the previous working directory.

Real filesystem paths must be prefixed to distinguish them from drive paths:
- `up ./notes.txt` — upload a local file
- `up notes.txt` — would look for `notes.txt` in the current drive folder

Tab completion covers command names, per-command flags, drive filenames (from in-memory cache, zero network), and real filesystem paths when prefixed with `./` or `../`.

---

## Commands

---

### `up <target> [options]`

Upload a file, directory, glob, or text.

| Argument / Flag | Description |
|---|---|
| `<target>` | Local file path, glob (`"*.py"`), `-` for stdin, or a literal string with `--text`. |
| `-k, --key <key>` | Set a custom key. Format: `[a-zA-Z0-9_\-]{1,64}`. Free plan and above. Rejected if taken. |
| `--expires <duration>` | Key expiry: `7d`, `24h`, `30m`. Capped at plan maximum. Defaults to plan maximum if omitted. |
| `--public` | List the file publicly on explore and your profile. |
| `--burn` | Invalidate the key after the first view. |
| `--password <pw>` | Require a password to access the key. Starter/Pro only. |
| `--encrypt <passphrase>` | Client-side AES encryption before upload. Server never sees plaintext. Use `--decrypt` to read back. |
| `--tag <tag>` | Add a tag. Repeatable: `--tag python --tag snippet`. |
| `--text` | Treat `<target>` as literal text content, not a filename. |
| `--fork` | After uploading, immediately fork the result (rarely needed; mainly for scripts). |

Uploading a directory or glob creates a folder automatically. Files are uploaded individually into it.

---

### `get <key|url> [options]`

Download a file to disk.

| Flag | Description |
|---|---|
| `<key\|url>` | Bare key (`xK9mZ2`), full URL, or a share URL containing `?t=`. Share URLs claim a folder share. |
| `-n, --name <filename>` | Save with a different filename instead of the original. |
| `--fork` | Fork the file into your own account instead of downloading. A new key is created under your ownership. |
| `--decrypt <passphrase>` | Decrypt client-side encrypted content after download. |
| `--stdout` | Write content to stdout instead of a file. Enables piping: `drp get xK9mZ2 --stdout \| grep foo` |

---

### `cat <ref> [options]`

Display a file's content in the terminal with syntax highlighting.

| Argument / Flag | Description |
|---|---|
| `<ref>` | A key (`xK9mZ2`) anywhere, or a filename in the current drive folder (shell only — resolved to a key automatically). |
| `--decrypt <passphrase>` | Decrypt client-side encrypted content before display. |
| `--parse` | Parse and pretty-print. JSON is formatted with indentation and colour. CSV is rendered as a table with box-drawing characters. |
| `--field <name\|index>` | Extract a single field. For JSON: dot-notation key (`user.email`). For CSV: column name or 0-based index. Implies `--parse`. |
| `--highlight <language>` | Force a syntax lexer. E.g. `--highlight python`. Overrides auto-detection. |

---

### `cp <src> <dest>`

Copy files between the real filesystem and the drive, or within the drive. Shell only.

| Pattern | Behaviour |
|---|---|
| `cp ./local.txt .` | Upload local file into the current drive folder |
| `cp ./local.txt projects/` | Upload into a named subfolder |
| `cp file.txt ../` | Download drive file to the real filesystem (your launch directory) |
| `cp file.txt copy.txt` | Duplicate a file within the drive under a new key |
| `cp file.txt projects/` | Copy a file into a subfolder within the drive |

Progress bar is shown for both uploads and downloads.

---

### `mv <src> <dest>`

Rename or move a file within the drive. Shell only. Does not re-upload — updates the filename and folder membership server-side.

---

### `rm <ref> [options]`

Delete a file or folder.

| Flag | Description |
|---|---|
| `--recursive` | Required to delete a non-empty folder. Without it, non-empty folders are rejected. |

---

### `ls [path]`

List files and folders.

| Flag | Description |
|---|---|
| `--export` | Output as JSON. Useful for scripting. |
| `--sort <field>` | Sort by `name`, `size`, or `exp` (expiry). |

- **Outside shell**: reads the local session cache. Instant, no network. Shows files uploaded in this session only.
- **Inside shell**: fetches the current drive folder from the server. Shows subfolders, filenames, sizes, expiries, and keys.

---

### `cd <path>`

Change the virtual working directory. Shell only.

```
cd projects          # into a subfolder of current location
cd ..                # up one level
cd /                 # back to your drive root
cd @otherusername    # into another user's public drive (read-only)
```

`cd @username` is the standard way to browse another user's public files. All read commands (`ls`, `cat`, `get`) work normally. Write commands (`up`, `rm`, `mv`) are rejected.

---

### `mkdir <name>`

Create a folder at the current drive location. Shell only.

---

### `edit <filename> [options]`

Fetch a file from the current drive folder, open it in `$EDITOR`, and re-upload it if the content changed. Shell only. Resolves filenames to keys automatically.

| Flag | Description |
|---|---|
| `--editor <editor>` | Override `$EDITOR`. E.g. `--editor nano`. |
| `--decrypt <passphrase>` | Decrypt before editing, re-encrypt before re-uploading. |

If nothing changed, no upload is performed.

---

### `fork <key>`

Fork a file you don't own. Creates a copy in your account with a new key and your plan's default expiry. The original is unaffected.

---

### `share [target] [options]`

Create and manage share tokens for folders. Shell only.

| Subcommand | Description |
|---|---|
| `share` | Create a share token for the current folder |
| `share <folder>` | Create a share token for a specific folder |
| `share list [folder]` | List all active tokens for a folder |
| `share revoke <id>` | Permanently revoke a token |

| Flag | Description |
|---|---|
| `--write` | Grant write access (recipient can upload into the folder) |
| `--admin` | Grant admin access (recipient can delete and rename) |
| `--expires <duration>` | Token expiry. E.g. `7d`, `30d`. |

---

### `ask "<question>"`

Ask the drp help bot a question. Conversation history is stored per account (last 20 exchanges). Works inside and outside the shell.

---

### `ping`

Check connectivity to the server and print round-trip latency.

---

### `status`

Display account info: username, plan, storage used and available, file count, folder count.

---

### `login`

Authenticate interactively. Prompts for username and password. The bearer token is stored in config. Anonymous accounts (unverified email) cannot log in via email — username only.

---

### `logout`

Revoke the current bearer token on the server and clear local config.

---

### `token create|list|revoke`

Manage account-level API tokens. These are separate from the session token used by `login` and are intended for scripts and integrations.

| Subcommand | Description |
|---|---|
| `token create [--label <n>]` | Create a token. Shown once — save it immediately. |
| `token list` | List all active tokens with labels and last-used timestamps. |
| `token revoke <id>` | Permanently revoke a token. |

---

### `getkey <filename>`

Print the key for a file in the current drive folder, looked up by filename. Shell only. Useful for scripting.

---

### `setkey <filename> <newkey>`

Rename a file's key. Shell only. The old key stops working immediately.

---

### `setup`

First-time configuration wizard. Sets the server URL and writes the initial config file.

---

## Encryption

`up --encrypt <passphrase>` performs client-side AES encryption before the file leaves the machine. The server receives and stores opaque bytes and has no access to the passphrase or the original content. Decrypt with `cat --decrypt <passphrase>` or `get --decrypt <passphrase>`.

---

## Crash Reporting

Every unhandled exception — from the CLI or the web — must result in a GitHub issue on first occurrence. This is non-negotiable. Crashes that don't file issues are invisible.

**Pipeline:** exception → fingerprint (SHA-256 of type + traceback) → deduplicate in `CrashReport` table → if first occurrence, POST to GitHub Issues API using `GITHUB_ISSUES_TOKEN`. Subsequent occurrences increment `hit_count` only. The filed issue URL is stored on the `CrashReport` record.

**CLI:** unhandled exceptions are caught by the top-level handler in `cli/crash/reporter.py`, serialised with exc type, message, traceback, CLI version, Python version, platform, and command, then POSTed to `/api/v1/crash/` in a background thread. The user sees a one-line message. The CLI exits normally.

**Web:** Django's `server_error` handler (triggered on any unhandled 500) must call the same `maybe_file_issue()` logic. The request context (URL, method, user if authenticated) should be included in the issue body. The user sees the standard error page.

**Required env vars:** `GITHUB_ISSUES_TOKEN` (GitHub PAT with `repo` scope) and `GITHUB_REPO` (default `vicnasdev/drp`). Without `GITHUB_ISSUES_TOKEN` the deduplication still works but no issue is filed — this should be treated as a misconfiguration in prod.

---

## Billing

The `billing` app receives Lemon Squeezy webhooks. Successful payment events set the plan on the user profile. Cancellation or expiry downgrades it. The webhook validates the `LEMONSQUEEZY_SIGNING_SECRET` HMAC signature on every incoming request.