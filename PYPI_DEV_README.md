# drp-dev — share text & files from your terminal

> **Development build** — may be unstable. For stable releases: `pipx install drp`.
>
> **Website:** [dev.drp.vicnas.me](https://dev.drp.vicnas.me) — dev server for testing.

```bash
pipx install drp-dev
drp setup
drp up "hello world"        # → https://dev.drp.vicnas.me/a1b2c3/
```

## Features

| Feature | Command |
|---|---|
| Upload text | `drp up "hello"` or `echo text \| drp up` |
| Upload file | `drp up report.pdf` |
| Custom key | `drp up logo.png -k logo` |
| Burn after reading | `drp up "secret" --burn` |
| Password protect | `drp up data.csv --password` |
| Retrieve text | `drp get <key>` |
| Download file | `drp get -f <key>` |
| List drops | `drp ls` |
| Organize | `drp collection new "notes"` |
| Interactive shell | `drp shell` |
| Lock existing drop | `drp lock <key>` |

**Embed anywhere:** `dev.drp.vicnas.me/embed/<key>/` (iframes, markdown)
**Raw access:** `dev.drp.vicnas.me/raw/<key>/` (curl, scripts, CI)

## Plans

Anonymous uploads work instantly — no account needed. [Sign up free](https://drp.vicnas.me/auth/register/) for longer expiry, or upgrade to [Starter/Pro](https://drp.vicnas.me/help/plans/) for collections, passwords, API tokens, server-side uploads, and more.

## Stable vs Dev

| | `drp` (stable) | `drp-dev` (dev) |
|---|---|---|
| **Source** | `main` branch | `dev` branch |
| **Install** | `pipx install drp` | `pipx install drp-dev` |

## Links

- **Website:** [dev.drp.vicnas.me](https://dev.drp.vicnas.me)
- **Docs:** [drp.vicnas.me/help](https://drp.vicnas.me/help/)
- **CLI reference:** [drp.vicnas.me/help/cli](https://drp.vicnas.me/help/cli/)
- **Stable package:** [pypi.org/project/drp](https://pypi.org/project/drp/)
- **Source:** [github.com/vicnasdev/drp](https://github.com/vicnasdev/drp)

## License

CLI: MIT.
