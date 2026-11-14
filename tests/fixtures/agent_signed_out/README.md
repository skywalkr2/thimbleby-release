# Signed-out messages of the command-line agents

One file per catalog entry that runs a program (`<entry id>.txt`), holding exactly what the program printed, on its output and
its error stream together, when it was run signed out (for example with an empty home folder) in the way the catalog entry
runs it. `tests/test_agent_signed_out.py` reads every file here and checks the account is told it is not signed in.

Only a real capture belongs here: nothing is written by hand. An entry with no file shows as an expected failure in that test until someone adds its file.
