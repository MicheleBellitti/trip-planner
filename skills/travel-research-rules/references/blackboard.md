# The blackboard: /workspace

Read this when you read or write a file on the blackboard and need the exact rules. The core
SKILL.md says when.

The agents share one filesystem. Structured data travels through these files, never through
messages.

| File | Writer | Readers |
|---|---|---|
| `shared/request.json` | coordinator, once, the request verbatim | everyone |
| `shared/constraints.json` | coordinator only | everyone |
| `results/flights.json` | flights only | coordinator, activities, transport |
| `results/lodging.json` | lodging only | coordinator, activities, transport |
| `results/activities.json` | activities only | coordinator, transport |
| `results/transport.json` | transport only | coordinator |

- **One writer per file.** Never write a file you do not own, not even to fix it: ask its
  writer through the coordinator.
- **Never half a file.** A writer writes a temp file and renames it over the old one, so a
  reader never sees a partial JSON: `write_result.py` does it. An agent without bash writes the
  complete file in one `write` call, never in pieces and never by appending.
- **`version` and `updated_at`.** Every file except `request.json` carries `version` (1 for the
  first write, +1 at every rewrite) and `updated_at` (when it was written: an instant with
  offset; an agent without a clock uses today's date at `T00:00:00+00:00`). `request.json` is
  written once, verbatim: cite it as `request.json`.
- **Cite what you used.** Your reply names the version you wrote and the version of every file
  you read. A file that is missing or does not parse: read it once more, then report it.
- Read only the files your task needs. A file you just wrote needs no read-back: the script's
  output (or, without bash, the `write` result) is the confirmation.
