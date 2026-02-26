# drp-cli — share text & files from your terminal

> **Development build** — may be unstable. For stable releases: `pipx install drp`.
>
> **Website:** [drp.fyi](https://drp.fyi) — try it now, no account needed.

```bash
pipx install drp-cli
drp setup
drp up "hello world"        # → https://drp.fyi/a1b2c3/
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

**Embed anywhere:** `drp.fyi/embed/<key>/` (iframes, markdown)
**Raw access:** `drp.fyi/raw/<key>/` (curl, scripts, CI)

## Plans

Anonymous uploads work instantly — no account needed. [Sign up free](https://drp.fyi/auth/register/) for longer expiry, or upgrade to [Starter/Pro](https://drp.fyi/help/plans/) for collections, passwords, API tokens, server-side uploads, and more.

## Stable vs Dev

| | `drp` (stable) | `drp-cli` (dev) |
|---|---|---|
| **Source** | `main` branch | `dev` branch |
| **Install** | `pipx install drp` | `pipx install drp-cli` |

## Links

- **Website:** [drp.fyi](https://drp.fyi)
- **Docs:** [drp.fyi/help](https://drp.fyi/help/)
- **CLI reference:** [drp.fyi/help/cli](https://drp.fyi/help/cli/)
- **Stable package:** [pypi.org/project/drp](https://pypi.org/project/drp/)
- **Source:** [github.com/vicnasdev/drp](https://github.com/vicnasdev/drp)

## License

CLI: MIT.
