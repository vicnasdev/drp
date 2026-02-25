# drp-cli

> **⚠️ Development Version** — This is the development build of the drp command-line tool. It may be unstable and less secure than production releases. Use at your own risk.
>
> For the stable package, install **[drp](https://pypi.org/project/drp/)** instead:
> ```
> pipx install drp
> ```
> For the hosted service, visit **[drp.fyi](https://drp.fyi)**.

---

Drop files or paste text from the command line — get a link instantly.

```bash
pipx install drp-cli
drp setup && drp up "hello world"
```

## Usage

```bash
drp up "some text"           # upload text
drp up file.pdf              # upload a file
echo "piped" | drp up        # pipe from stdin
drp get <key>                # retrieve text
drp get -f <key>             # download file
drp ls                       # list your drops
drp rm <key>                 # delete a drop
```

## Why drp-cli?

This is the **development/preview** channel. It tracks the `dev` branch and receives changes before they are validated for stable release.

| | `drp` (stable) | `drp-cli` (dev) |
|---|---|---|
| **Source** | `main` branch | `dev` branch |
| **Stability** | Tested, tagged releases | May break between updates |
| **Security** | Reviewed before release | May contain unreviewed changes |
| **Install** | `pipx install drp` | `pipx install drp-cli` |

## Links

- **Stable package:** [pypi.org/project/drp](https://pypi.org/project/drp/)
- **Homepage:** [drp.fyi](https://drp.fyi)
- **Source:** [github.com/vicnasdev/drp](https://github.com/vicnasdev/drp)

## License

CLI (`cli/`): MIT.
