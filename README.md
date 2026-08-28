# drp

instant clipboard & file sharing

![version](https://img.shields.io/github/v/tag/vicnasdev/drp)
![license](https://img.shields.io/badge/CLI-MIT-green)
![python](https://img.shields.io/badge/python-3.10+-blue)

Share text, code snippets, and files from your terminal in seconds. Get a link, share it anywhere.

```bash
pipx install drp
drp setup
drp up "hello world"        # get a shareable link
```

## What can drp do?

```bash
drp up notes.md              # upload a file, get a link
echo "secret" | drp up --burn # burn after first view
drp up photo.png -k avatar   # custom key
drp get mykey                 # fetch text back
drp get -f report             # download a file
drp ls                        # list your drops
drp lock mykey                # password-protect (paid)
drp shell                     # interactive REPL
```

**Embed anywhere:** images, iframes, raw text via embed and raw URL routes, including markdown image embeds.

**Collections:** organize files into folders with sub-folders and shell navigation.

**Plans:** anonymous drops work instantly. Sign up free for longer expiry, or go Starter/Pro for collections, passwords, API tokens, and more.

## Links

- **PyPI (stable):** [pypi.org/project/drp](https://pypi.org/project/drp/)
- **PyPI (dev):** [pypi.org/project/drp-dev](https://pypi.org/project/drp-dev/)
- **Repository:** [github.com/vicnasdev/drp](https://github.com/vicnasdev/drp)

## Self-hosting

> Source-available for personal/internal use, see [LICENSE](LICENSE).

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.com?referralCode=ZIdvo-)

See the repository docs for setup instructions and environment variables.

### Commercial License

Want to deploy drp for your organization? A **Commercial Self-Hosted License** is available. See [COMMERCIAL.md](COMMERCIAL.md) for full terms.

## License

Server: source-available, personal/internal use only, see [LICENSE](LICENSE).
CLI (`cli/`): MIT.
