# Changelog

Each version has one section, headed `## <version> (<date>)`. A release's notes are its section. Until the version is
tagged its heading says `(unreleased)`; the date is set to the tag's day in the commit that is tagged.

## 0.1.0 (unreleased)

The first alpha. It is for people who want to try it and say what is wrong: expect rough edges, and keep your own copies of
anything you cannot lose. The installers are not signed yet, so macOS and Windows will show a warning the first time you
open the app.

What you can do now:

- **Install it and start working in minutes.** Install the package file (or the unsigned Windows or macOS installer), run
  `thimbleby`, and a workspace is made in your home folder and opened in your browser. A setup walkthrough asks for your
  name and time zone, what the assistant is for (your own life, a job, a business), your AI account, your mail and
  calendar, backups and the people you work with. Every step can be skipped and finished later.
- **Bring your own AI account.** Use a key from your AI service, any compatible endpoint, an aggregator, or a program on
  your computer that is already signed in. Adding an account tests it first and shows what the test costs. Nothing is spent
  on your own material until you press Start, and you see an estimate before it.
- **See what needs you on Today.** Each line starts with what to do. The assistant reads what you hand in (notes,
  minutes, messages, files, and mail and calendar through an add-on) and proposes actions with owners and dates,
  questions for people, facts and notes.
- **Review the assistant's work.** Keep a proposal, change it, send it back with a note, or undo it. The assistant learns
  from each correction, and what it learned is listed for you to keep or drop.
- **Send nothing by accident.** Messages, pages and files wait under Follow-ups until you approve exactly what will go. By
  default you copy a message and send it from your own mail or chat.
- **Keep a schedule.** The Schedule shows meetings and what is due by day, week, month or on a timeline, with days off and
  time away taken into account.
- **Keep your life and your work apart.** Your own life, a job and a business are separate sides, each with its own
  to-dos, questions, notes and people.
- **Ask the assistant.** Ask in your own words how to do something in the app or about your work; it answers from the user
  guide, your settings and your records, and shows the words its answer rests on.
- **Keep your records safe.** Back up to a folder you choose, with an optional key to encrypt them, and restore a whole workspace from
  a backup. Two computers can share a workspace through a synced folder.
- **Add what it needs.** Add-ons (mail, calendar and others) can be installed from the Add-ons screen with their
  checksums checked. You can define your own with the plugin kit, documented in `docs/plugin-guide.md`.
- **Use it by keyboard, in a narrow window, with a screen reader.** No screen scrolls sideways, and status is never shown
  by color alone.

Known limits: the Mac installers need macOS 15 or later; the installers aren't signed; a new version is offered on Today and from
the menu but never installed unasked (a command-line install runs the install step again with the newer file); and there's no hosted version.

Found something wrong? Open an issue here with the bug form.
