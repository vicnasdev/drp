# [drp](https://drp.fyi) — instant clipboard & file sharing

![version](https://img.shields.io/github/v/tag/vicnasdev/drp)
![license](https://img.shields.io/badge/CLI-MIT-green)
![python](https://img.shields.io/badge/python-3.10+-blue)

Share text, code snippets, and files from your terminal in seconds. Get a link, share it anywhere.

**[drp.fyi](https://drp.fyi)** — try it now, no account needed.

```bash
pipx install drp
drp setup
drp up "hello world"        # → https://drp.fyi/a1b2c3/
```

## What can drp do?

```bash
drp up notes.md              # upload a file → get a link
echo "secret" | drp up --burn # burn after first view
drp up photo.png -k avatar   # custom key → drp.fyi/f/avatar/
drp get mykey                 # fetch text back
drp get -f report             # download a file
drp ls                        # list your drops
drp lock mykey                # password-protect (paid)
drp shell                     # interactive REPL
```

**Embed anywhere** — images, iframes, raw text:
```
https://drp.fyi/embed/mykey/    ← embeddable viewer
https://drp.fyi/raw/mykey/      ← plain text (curl-friendly)
![img](https://drp.fyi/raw/avatar/)  ← markdown image
```

**Collections** — organize files into folders with sub-folders and shell navigation.

**Plans** — anonymous drops work instantly. [Sign up free](https://drp.fyi/auth/register/) for longer expiry, or go [Starter/Pro](https://drp.fyi/help/plans/) for collections, passwords, API tokens, and more.

## Links

- **Website:** [drp.fyi](https://drp.fyi)
- **Help & docs:** [drp.fyi/help](https://drp.fyi/help/)
- **Plans & pricing:** [drp.fyi/help/plans](https://drp.fyi/help/plans/)
- **CLI reference:** [drp.fyi/help/cli](https://drp.fyi/help/cli/)
- **PyPI (stable):** [pypi.org/project/drp](https://pypi.org/project/drp/)
- **PyPI (dev):** [pypi.org/project/drp-dev](https://pypi.org/project/drp-dev/)

## Self-hosting

> Source-available for personal/internal use — see [LICENSE](LICENSE).

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.com?referralCode=ZIdvo-)

See [drp.fyi/help](https://drp.fyi/help/) for setup instructions and environment variables.

### Commercial License

Want to deploy drp for your organization? A **Commercial Self-Hosted License** is available.

[Purchase & generate your license PDF →](https://drp.fyi/billing/licensing/)
See [COMMERCIAL.md](COMMERCIAL.md) for full terms.

## License

Server: source-available, personal/internal use only — see [LICENSE](LICENSE).
CLI (`cli/`): MIT.