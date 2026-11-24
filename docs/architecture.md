# Architecture

A short map of how Thimbleby is put together, for someone reading the code for the first time. It describes what the code
does; the plugin contract is in [`plugin-guide.md`](plugin-guide.md).

## The parts

- **`engine/`** is the core, in Python. It holds the records, the changeset applier, the history, the assistant's task
  runner, the checks, the worker that runs jobs, the command line and the backups.
- **`api/`** is the web API, built with FastAPI. Its routes return typed models, and the screens' client is generated from
  the API's published schema.
- **`web/`** is the screens, in React and TypeScript. The API serves the built screens.
- **`plugins/`** holds the define-your-own kit and an example plugin. Anything that belongs to one kind of work is a plugin;
  the core imports nothing from a plugin.
- **`deploy/`** holds what the installers for Windows and macOS need, and **`workspaces/`** holds two made-up workspaces for
  tests and the demo.

## The loop

The app watches the sources a person chooses (mail, calendars, folders, feeds) through connectors. What it reads becomes
an input. For each input the assistant is asked for a changeset: proposed changes to records, each with the words from the
source that justify it. Checks run on the changeset, and only the applier writes records. Anything that would go out to
another person is a draft that waits for the person's approval of that exact content.

## Records and history

A workspace is a folder with a SQLite database as its record of truth. Every change is applied as an op, and every op is
written to the history in the same transaction, which is what makes Undo possible. A readable export of the records sits
beside the database, and `thimbleby import` loads it back.

## The AI layer

The assistant is reached through one provider layer, `engine/ai/`. Each kind of service has an adapter that turns a task
into that service's request and its answer into a result; the rest of the code never sees a vendor. The person brings their
own account, and prompts are templates, not code.

## Plugins

A plugin declares in its manifest what it provides and what it may reach, and imports only the plugin API. Plugins work
together only through the core: shared records, events, and versioned interfaces.

## Where the network is touched

Reads and writes to outside services go through one web client that reaches only the hosts it was given, over https, and
that follows a redirect only to a host it was given. In local mode the app listens only on this computer.
