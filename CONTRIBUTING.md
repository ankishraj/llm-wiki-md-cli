# Contributing

Thank you for your interest in `llm-wiki-md-cli`.

## Status: not accepting contributions

This project is **not accepting pull requests or external code contributions at
this time.** PRs will not be reviewed or merged.

You are very welcome to:

- **Open an issue** to report a bug or suggest an idea. Note that there is no
  commitment to triage, respond, or fix on any timeline — issues are read as
  time allows.
- **Fork the project** and build your own version. This is encouraged. The MIT
  License lets you use, modify, and redistribute freely; it only requires that
  you keep the copyright and license notice. A credit back to `llm-wiki-md-cli`
  by ankishraj is appreciated but not required.

If this policy changes in future, this file will be updated.

## Running the tests (for forkers)

If you fork and want to validate changes:

```bash
pip install jsonschema portalocker pytest
make test           # or: PYTHONPATH=tools/wiki-src python -m pytest tools/wiki-src/tests -q
make wiki           # rebuild the zipapp + checksum after changing CLI source
```

The CI workflow (`.github/workflows/wiki.yml`) additionally checks that
`tools/wiki.pyz` reproduces byte-for-byte from source and matches its committed
checksum.
