# Thimbleby

Thimbleby is a daily assistant for anyone juggling work. It watches the sources you choose (mail, calendars, folders,
trackers, feeds), keeps track of what you promised and what was promised to you, and gets the next step ready. Its
assistant, Reginald by default (you can rename it), drafts updates, questions and action items with the evidence for each,
and gives you one screen to review, correct and send them out. **The AI drafts; you approve everything that goes out.**

It runs on your own computer, reachable only from that computer, and works with the AI account you bring: native vendor
APIs, any OpenAI-compatible endpoint, aggregators or command-line agents. Branding, wording, schedules and storage are
settings, so you can change an installation without changing code.

The core is a generic base. Everything specific to one kind of work comes from plugins; this repository holds the core,
the define-your-own kit and an example plugin. The plugin contract is [`docs/plugin-guide.md`](docs/plugin-guide.md),
generated from the code.

## Install

- [`docs/install.md`](docs/install.md): the installers and the package file, for people who never open a terminal.
- [`docs/getting-started.md`](docs/getting-started.md): from the install to your first result, step by step, with what
  each step costs.

From a checkout you need Python 3.12 or newer with [uv](https://docs.astral.sh/uv/), and Node 22.12 or newer with npm:

```
uv sync
npm --prefix web ci && npm --prefix web run build
uv run thimbleby
```

The first run makes your workspace and opens a setup walkthrough. Nothing is spent on AI until you press Start.

## Checks

```
uv run ruff check . && uv run ruff format --check . && uv run pytest && uv run python -m engine.selfcheck
npm --prefix web test && npm --prefix web run build && npm --prefix web run e2e
```

## Releases

Each version is a tag here. Its release on the Releases page carries the installers for an Apple-chip Mac, an Intel Mac and
Windows, the package file with its install scripts, and a `SHA256SUMS` file for each installer. The installers are
unsigned; [`docs/install.md`](docs/install.md) says how to open them the first time. A release's notes are that version's section of [`CHANGELOG.md`](CHANGELOG.md).

## Reporting a bug

Found something wrong? Open an issue on this repository with the **Bug report** form. Say:

- the steps from a fresh start (opening the app, or a new workspace), in order;
- what happened, and what you expected;
- the version, shown at the top of Settings in the app, or the line in `EXPORTED_FROM` if you run from a checkout;
- your computer and system, for example a Mac with an Apple chip on macOS 15, or Windows 11.

This repository is public, so leave anything private out of an issue, and cover it in any picture. A security problem is
never an issue: report it through the Security tab, as the next section says.

## Security

Report a security problem privately, through **Report a vulnerability** on this repository's Security tab, never in public.
[`SECURITY.md`](SECURITY.md) says what to include.

## This repository

This repository is an export of tested snapshots. The product is developed elsewhere, and each snapshot is published here
after its checks pass. It takes no pull requests, because a change made here would be overwritten by the next snapshot. It
welcomes bug reports as issues (see Reporting a bug).

## License

[Functional Source License 1.1, Apache 2.0 future license](LICENSE) (FSL-1.1-ALv2). This is source-available, not open
source, until each release converts. You may use, read, change and run it for any purpose, at home and at work, inside your
organization, except offering it, or something substantially like it, to others as a commercial product or service. Each
release becomes available under the Apache License 2.0 two years after it is published. Keep the copyright notice and the
[`NOTICE`](NOTICE) file. The license includes a patent license, which ends for anyone who sues over patents in the
software.
