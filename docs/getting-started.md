# Getting started

This page takes you from a computer with nothing on it to your first result: the assistant has read your mail and
turned it into actions and questions you can look over. It takes about 10 to 20 minutes of your time. The assistant spends nothing
on your own material until you press **Start** on Today's Start line at the very end, and you see the estimate first. The one thing before that
which costs anything is the check of your AI account, which you start yourself and which shows its cost beforehand (in the walkthrough's AI account step).

You do three things in order: install the app, open it (which starts your own workspace), and follow the setup
walkthrough that opens by itself.

## 1. Install

You need an AI account of your own with your AI service (a key for it, or a program on your computer that is already
signed in). The app does not come with one, and no AI service is chosen for you.

**The installer** (no terminal, no Python, no Node). Download the one for your computer from the Releases page:

- a Mac with an Apple chip: `Thimbleby-<version>-macos-arm64.dmg` (macOS 15 or later);
- a Mac with an Intel chip: `Thimbleby-<version>-macos-x86_64.dmg` (macOS 15 or later);
- Windows: `Thimbleby-<version>-windows-x64-setup.exe` (installed for you alone, no administrator password).

The installers are unsigned, so the system asks you to confirm the first open, once. On a Mac, opening it says Apple could
not verify it: open **System Settings › Privacy & Security**, scroll to the line about Thimbleby, and click **Open Anyway**,
then **Open**. On Windows, the setup says "Windows protected your PC": click **More info**, then **Run anyway**.
`docs/install.md` has the same steps and the details. Then open the app. It opens in its own window, not in a browser, and
the setup walkthrough starts in it. Installing costs nothing and changes nothing outside the app's own folders.

### Install from the command line instead

For people who prefer a terminal, or use Linux. You need **uv**, the Python package tool; its own documentation shows how,
and it fetches the right Python for you. Then, in a terminal, in the folder where you saved the package file and the
install script for your computer:

```sh
sh install.sh thimbleby-<version>-py3-none-any.whl                                  # macOS, Linux
powershell -ExecutionPolicy Bypass -File install.ps1 thimbleby-<version>-py3-none-any.whl   # Windows
```

Or, from a checkout of the source, with Python 3.12 or newer with uv, and Node 22.12 or newer with npm:

```sh
uv sync
npm --prefix web ci && npm --prefix web run build
```

(`docs/install.md` has the details, updating, and restoring from a backup.)

## 2. Open it and start your own workspace

A workspace is one folder that holds your work. The first time you open the installed app, it makes your workspace in the
system's app-data folder and opens the setup walkthrough in its window. Nothing else is needed. Closing the window leaves the
app running; its menu-bar item (Mac) or tray item (Windows) opens it again, restarts it or quits it.

**If you installed from the command line**, keep the workspace in your home folder, not in a temporary folder: the system
empties temporary folders when the computer restarts, and your setup would go with them.

```sh
thimbleby
```

That's the only command to remember. From a checkout, run `uv run thimbleby` in its folder the first time; on macOS and
Linux that also makes `thimbleby` work in any folder from then on. The first time, it makes your
workspace in a folder called `Thimbleby` in your home folder (a workspace an earlier version made in `Cockpit` is kept in use) and opens it in your browser, where the walkthrough starts.
Every time after, the same command reopens the workspace you used last. It runs on your own computer, reachable only
from it. If the browser doesn't open, copy the link it prints. Leave the terminal window open while you work: closing it
stops the app.

To keep a workspace somewhere else, or have more than one (command line): `thimbleby init <folder>`, then
`thimbleby serve -w <folder>`. After that, `thimbleby` alone reopens whichever you used last.

**Updating.** The installed app looks for a newer version once a day and offers it as a line on Today; **Check for a new
version** in its menu-bar or tray item looks at once. Choosing the update copies your work first, installs, and opens the new
version. A command-line install updates with `thimbleby update` (a checkout) or by running the install step again with the
newer package file (a package install).

Nothing is spent so far, and nothing has left your computer.

## 3. The setup walkthrough

The first time you open a new workspace, the walkthrough opens by itself on **Welcome**: *About 10–20 minutes. You can stop
and come back.* It says what you will need (an AI account, your mail and calendar if you want them read, a place for
backups) and that nothing is read or spent until you say so. Press **Start**. The steps are Welcome, You, What it's for,
Your AI account, Mail and calendar, Backups, People and Done, one screen at a time, in the order you need
them. Every step says why it matters and can be skipped and done later. **Finish later** closes it; it then stays closed until
you open it again from the **Setup** line on Today, from **Help**, or from **Settings**. It remembers where you were, also
after a restart.

### You

Your name, the workspace's name and your time zone, in one form. Press **Save**. Your name makes your own record in
People, so the assistant knows who "me" is when it files an action.

*Cost: nothing.* *If it fails:* a message under the form says what was refused (for example a time zone it does not know);
fix that field and save again. What you typed stays in the form.

### What it's for

Tick **A job** or **My own business** if you use the assistant for either as well. Your own life is always included. A
job asks what your employer is called; a business asks its name and, if you like, its projects, one on each line. Each
one becomes a side of your work, so bills, to-dos and people land on the right side. Leave both empty to go on without
either; you can add one later in Settings, under Your business.

*Cost: nothing.*

### Your AI account

Pick your AI service by name, make a key on that service's own page, paste it here, and press **Check**. The app asks the
service for the models it offers; pick one for everyday work and, if you like, a stronger one for harder work. Then choose
what the assistant may see. **Your notes, mail and meetings are internal material, so tick Internal**; a new account sees
only open material until you raise it. Press **Add account**, then **Test again**: the app sends one small test request
for each kind of work to check that the account answers.

**What it may spend** sits below the account: the amount above which the assistant asks you first (it starts at $0.10) and
the most it may spend in a day (it starts at $2.00). You can change both here or later in Settings.

Your key stays on this computer, in a private folder only you can read. The settings refer to it and never hold it.

*Cost: the test is the one thing in setup that spends money, and you start it.* It sends a few small requests to your AI
service, normally a fraction of a cent in all. The button shows the estimate when the app can work it out, and when you add an
account the app asks first if the estimate is above the amount you set under *What it may spend*. None of your own material is sent. Nothing
else is spent here.
*If it fails:* the test says in plain words what went wrong. The usual causes are a key copied only in part, a key that has
been switched off, an account with no credit, or a service that is busy; copy the key again, check the service's account
page, or try again in a minute. Press **Test again** after you change something.

### Mail and calendar

The assistant reads your mail and calendar so you do not have to hand things in one by one. It only reads: it never sends,
moves or deletes anything.

The screen lists the services you can connect, each with what it reads, who made it and what it can reach.

- **Press Connect <the service>.** If the service is not on this computer yet, the app installs it and turns it on (a
  service that is installed but off is turned on the same way). **How to get it** shows its instructions when it can't be
  fetched for you.
- **If the app says it needs a restart,** press **Restart to finish connecting** (a few seconds). The app restarts only
  when you press this button, and the walkthrough comes back at this screen. At most one restart is needed in the whole
  walkthrough, even if you connected more than one service first.
- **Then sign in.** The service's own sign-in page opens in this tab; you sign in there and allow reading. You come back
  to this screen.

After you sign in, the screen lists the accounts being read (your inbox and your main calendar) and asks who each is for:
you, or a job or business you named. Newsletters, sales and mailing lists are set aside by default; **Change** turns
that off. **What it holds waits for your Start on Today**, so you see a result without a surprise on the bill.
**Connect another account** adds a second one. You can choose other folders or calendars later from Settings, under
Connections.

If your mail service is not in the list, press **Add mail, calendar or folder**. That adds a mail folder from any mail
server (with an app password) or a calendar's private address.

*Cost: nothing here.* Reading costs nothing; the AI only works on what was read after your Start.
*If it fails:*
- If the install is refused, the row shows the app's own words (a release that does not match its checksum, or one that
  cannot be reached). Try again, or press **How to get it** for the add-on's instructions.
- If the app says it cannot restart itself, or does not come back within a minute: in the installed app, choose **Quit** in
  its menu-bar or tray item, then open the app again. On a command-line install, close the terminal's program with Ctrl+C
  and run the same `thimbleby serve` command again. The walkthrough opens at this screen.
- If signing in is refused, a message says so when you come back. Press **Sign in** again. If your service shows a warning
  page for this app, the screen says what that means for you.

### Backups

Choose a folder outside the workspace, such as one a cloud drive keeps, and press **Use this folder for backups**. The app
checks the folder first: it must be there, outside the workspace, and writable. Press **Check** to see it before you save.
The first backup is made on its own schedule, and the header shows its age once one has succeeded.

*Cost: nothing.* *If it fails:* the message says why the folder will not do (the drive is not connected, the folder is
inside the workspace, or the app cannot write in it). Choose another folder.

### People

Optional. Add the people you work with, so actions can name an owner. **Skipping is fine**: a name the assistant cannot
place becomes a question for you to answer, and you can add people at any time.

### Done

The last screen lists what was set up and what you skipped, each skipped item with a **Set up** button that takes you back
to it. Below that are optional extras for later: a starting template and other add-ons. None of them is needed to start.

Press **Go to Today**. The Done screen says what to do next: on Today, look over the estimated cost and approve the first items.

## Your first result

Today shows one line: **Start the assistant**, with how many items are waiting and about what they would cost together,
such as *Start the assistant: 14 items, about $0.30* (on a plan with an allowance instead of a price, it says the items use
your plan's allowance). Keyboard focus is on it when you arrive. Nothing has been sent to your AI service yet.

Press **Start** on that line. The assistant reads each item, one at a time, and files what it finds: actions with owners and
dates, questions, facts and notes, each with the words from your mail that justify it. Open **What changed** to look over
what it did. You can keep any change, change it, send it back with a note, or undo it. Nothing goes to another person
until you approve the exact words, and the app never sends anything by itself.

**What it costs:** the estimate on that line, shown before you press Start. A model whose price the app doesn't know is never
counted as free: its runs wait for your go every time, unless you say its account costs nothing more per run. After the first Start, the amount you set under
*What it may spend* applies: a run estimated above it asks you first, and a run below it starts on its own. The daily limit
stops new runs for the day.

You can also press **Hand something in** (or the `n` key) at any time to paste an email, minutes or a note.

## If you closed the walkthrough, or want to change something

- On Today, the **Setup** line shows how far you are and has **Continue setup**.
- **Help** has **Setup guide**, and **Settings** has **Open the setup guide**.
- Everything the walkthrough sets is also in **Settings** (You, Your business, AI and spending, Connections, Backups and Add-ons) and in **People** and **Projects** in the side menu.

## If something does not work

- **The page does not open (command-line install):** copy the link `thimbleby` printed into your browser. It only works on this computer. The installed app opens in its own window; choose **Open** in its menu-bar or tray item.
- **On a command-line install, the terminal says the workspace folder is not empty:** `thimbleby init` makes a new folder; give it a path that does not
  exist yet.
- **Setup has a step that stays "Not done yet":** open that screen. It says what is missing, and the step is done once the
  workspace shows it.
- **You want to start over:** from the command line, make a new workspace with `thimbleby init` in another folder. The old one is untouched.
- **The page says you're not signed in (a browser on a command-line install):** with the app running, `thimbleby open` opens it again, signed in.
- **You want everything gone:** on the command line, `thimbleby erase` lists exactly what a workspace holds (its records, history and backups) and deletes it after you confirm.
- **You want to try an add-on on made-up data first:** on the command line, `thimbleby demo` makes a sandbox of made-up people and projects. It is
  a place to try things, not a place to start your real work.
