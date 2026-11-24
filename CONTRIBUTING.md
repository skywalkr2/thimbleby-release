# Contributing

Thanks for looking. This page says how to help and what to expect.

## Bug reports are issues

The most useful thing you can do is report a bug. Open an issue with the **Bug report** form and say:

- the steps from a fresh start, in order;
- what happened, and what you expected;
- the version, shown at the top of Settings in the app, or the line in `EXPORTED_FROM` if you run from a checkout;
- your computer and system, for example a Mac with an Apple chip on macOS 15, or Windows 11.

This repository is public, so leave anything private out of an issue, and cover it in any picture.

A security problem is never an issue. Report it privately through **Report a vulnerability** on this repository's Security
tab; [`SECURITY.md`](SECURITY.md) says what to include.

## Pull requests stay closed

This repository is an export of tested snapshots. The product is developed elsewhere, and each snapshot is published here
after its checks pass, so a change made here would be overwritten by the next snapshot. For that reason pull requests are
not accepted. If you have a change in mind, describe it in an issue instead: what you want to be different and why.

## Plugins

Plugins are the way to add what one kind of work needs. They are separate packages, not changes to this repository. The
contract they build against is [`docs/plugin-guide.md`](docs/plugin-guide.md), generated from the code.

## Running the checks

To see the checks the snapshots pass, run them from a checkout; [`README.md`](README.md) lists the commands. How the parts
fit together is in [`docs/architecture.md`](docs/architecture.md).

## License

Your use of the code is under the [license](LICENSE).
