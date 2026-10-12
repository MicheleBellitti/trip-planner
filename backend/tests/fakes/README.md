# FakeManagedAgentsClient

`tests/fakes/__init__.py` is the offline Managed Agents client every consumer, sessions, routes,
jobs and CLI test runs against. It never talks to Anthropic, never opens a socket and never
spends money (CLAUDE.md, "Testing offline").

It implements `app.ma_client.ManagedAgentsClient` exactly (pyright checks it through
`_conforms()`), so the code under test can't tell it from `SdkManagedAgentsClient`. It works at
the seam's level, `RawEvent` dicts: SSE parsing (pings, `event: error`, payloads without
`type`), HTTP status mapping and SDK retries belong to `SdkManagedAgentsClient` and are tested in
`test_ma_client.py` over `httpx2.MockTransport` (see "Not the fake's job" below). It does four
jobs:

1. **Replays scripted event sequences** (JSONL), with the real API's stream semantics.
2. **Records everything the backend calls and sends**, in the exact JSON the real client would
   POST, with the streams that were open at send time.
3. **Round-trips custom tool results**: a script waits for the backend's `submit_plan` answer
   and branches on it (rejected, then accepted).
4. **Injects faults**: dropped streams, `event: error`, failing or hanging calls.

```python
from tests.fakes import FakeManagedAgentsClient

fake = FakeManagedAgentsClient.from_scenario("happy_path")   # tests/fixtures/ma/happy_path.jsonl
... run the consumer (or the app with the fake injected) ...
await fake.wait_until_done()       # every step ran (AssertionError after await_timeout)
fake.assert_script_done()          # re-raises the first ScriptMismatchError
assert fake.sent[0].open_streams == frozenset({"session"})   # stream open before the brief
assert fake.archived == [fake.session_id]
```

## Sessions

The fake has one **scripted session** (`session_id`, default `sesn_fake_0001`). It exists from
construction, `idle`, with `created_at = FAKE_EPOCH`, `list_cost_cents` (default 0) and
`budget_cents` (default None) from the constructor, so a resume test can follow it without
`create_session`. The first `create_session` call returns it (and records it in `created`);
later calls create unscripted sessions (`sesn_fake_extra_0001`, ...) that follow the same API
rules but have no script. `workspace_sessions=[SessionInfo, ...]` adds other sessions of the
workspace for `list_sessions` / `delete_session` (nightly sweep tests).

The scripted session's primary (coordinator) thread is `meta.primary_thread_id`, else
`sthr_fake_primary`; `list_threads` always returns it first (`agent_name="coordinator"`,
`parent_thread_id=None`, status = the session's).

## Stream semantics it reproduces

These are the API behaviours the consumer is built around (docs/managed-agents-notes.md §2d-§2f).
A fake that is more forgiving than the API would hide real bugs.

| Behaviour | What the fake does |
|---|---|
| A stream delivers only events emitted after it opens | `stream_session()` / `stream_thread()` are async context managers: entering registers the stream; an event is appended to the history and delivered only to the streams of its scope open at that moment. Each stream gets its own deep copy. |
| Thread streams don't replay either | Same rule per thread scope, plus a per-thread history for `list_thread_events`. Thread events never enter the session history. |
| History is ordered and paged | `list_events` pages the session history oldest first with an opaque cursor (`"p<offset>"`), honouring `limit` and the fake's `page_size` cap (constructor or `set`). `since` keeps events whose parsed `processed_at >= since` (instants compared, never strings; a naive `since` is a ValueError). An invalid cursor is `ApiRejectedError`. |
| Every event has `id` and `processed_at` | An emitted event without them is stamped: `sevt_fake_<n>` and `processed_at` = 1 ms after the latest `processed_at` the session has seen (`FAKE_EPOCH` for the first), formatted like the API (`2026-10-12T10:00:00.000Z`). Explicit values are kept as written. |
| Event ids are unique across sessions | Scripts use fixed ids, and `events.ma_event_id` is unique across the database, so the same scenario played twice into one database would store nothing the second time. `id_namespace="<ns>"` (constructor, `from_jsonl`, `from_scenario`) suffixes every scripted event id with `_<ns>`, rewrites every exact reference to it (`tool_use_id`, `await` matches, `stop_reason.event_ids`, ...) and makes generated ids `sevt_fake_<ns>_<n>`. `app.cli replay` passes a fresh one per run; tests on an emptied database don't need it. |
| Sent events are echoed | `user.message`, `user.custom_tool_result` and `user.interrupt` are appended to the history (and delivered to open session streams) as the API's echo, with a fresh id. `user.interrupt` gets an **empty** id, like the current API [SKILL]. |
| A second tool result for the same call has no effect | Recorded in `sent` (and consumed by `await` steps), echoed once only. A result for an id that is not an `agent.custom_tool_use` of the session is `ApiRejectedError`. |
| `session.status_idle` precedes the status write | With `status_lag: N` (a `set` step), the next N `retrieve_session` calls after an idle report `running`; archive/delete refuse the session meanwhile. |
| Archive/delete refuse a running session | `SessionBusyError` while the reported status is `running`. Archive then emits `session.status_terminated` (status `terminated`, every stream ends); archiving again is a no-op. Delete delivers `session.deleted` to open streams, ends them and forgets the session (404 afterwards). |
| Budget update must exceed consumption | `update_budget` raises `ApiRejectedError(error_type="budget_not_raised")` unless `budget_cents > list_cost_cents`; on success it is recorded in `budget_updates` and the fake emits `session.updated` with the new `budget`. |
| A user message at the budget is refused | After a `session.status_idle` with `budget_reached` and until a budget update (or `session.status_running`), `send_user_message` raises `ApiRejectedError` (400). Interrupts and tool results are still accepted. |
| A terminated session takes no events | Sends and `update_budget` on a terminated or archived session are `ApiRejectedError`. |
| Streams end on terminated/deleted | Emitting `session.status_terminated` or `session.deleted` on the session scope ends every open iterator normally; `session.thread_status_terminated` on a thread scope ends that thread's streams. Any other end is a `StreamDisconnectedError` (`disconnect`). |
| A mid-stream `event: error` or a dropped connection | `disconnect` (optionally with `error_type`, e.g. `overloaded_error`) makes the open stream(s) of a scope raise `StreamDisconnectedError` with that `error_type`. Events emitted while nothing is open reach only the history. |
| Threads can be archived | `archive_thread` marks the thread archived (`ThreadInfo.archived`) and records `(session_id, thread_id)` in `archived_threads` once. The primary thread can't be archived (`ApiRejectedError`). An `emit` to an archived thread's scope is a script mismatch. |
| Unknown sessions and threads | 404: `SessionNotFoundError` from every call, stream opening included. |
| `sessions.create` limits | `budget_cents` a positive int, `environment_id` set, at most 16 metadata pairs, keys <= 64 and values <= 512 characters, else `ApiRejectedError`. |

The tracked state follows the emitted events: `session.status_running` -> `running`,
`session.status_idle` -> `idle`, `session.status_rescheduled` -> `rescheduling`,
`session.status_terminated` -> `terminated`; `session.thread_created` registers a thread (from
`session_thread_id` and `agent_name`, status `running`); `session.thread_status_*` (on either
scope) set the thread's status; `session.usage` updates `SessionUsage` (USD `list_cost` only);
`session.updated` with a `budget` updates the cap; `agent.custom_tool_use` ids become valid
targets for tool results.

## The script driver

The script runs on one background task, the **driver**, started by the first
`create_session()` or stream opening on the scripted session (or explicitly by `fake.start()`,
e.g. to fill the history before a resumed consumer starts). Steps run in order; the driver
yields to the event loop between steps, and marks the script finished before yielding after the
last one (a test that has seen the last event sees a finished script).

Blocking steps (`await`, `await_call`, `await_stream`, `checkpoint`) wait at most
`await_timeout` seconds (constructor, default 5) or the step's own `"timeout"`; a timeout is a
`ScriptMismatchError`. Mismatches never raise inside the backend's call (that would turn a test
bug into a "failed plan" and hide it): they are recorded, the driver stops, and
`assert_script_done()` / `wait_until_done()` re-raise the first one. Every test that uses a
script ends with `fake.assert_script_done()` (after `await fake.wait_until_done()` when the
backend may still be acting).

Sends to the scripted session are queued for the driver in order. An `await` step consumes the
next queued sends; one that doesn't match is a mismatch. Sends no `await` consumed are listed in
`fake.unmatched_sends` (not an error: the API accepts them too).

## Script format

A script is a JSONL file in `backend/tests/fixtures/ma/<scenario>.jsonl`: one JSON object per
line, blank lines and lines starting with `#` ignored. Malformed steps are a ValueError at load
time. Each object has an `op`:

| `op` | Fields | Effect |
|---|---|---|
| `meta` | `description`, `request` (a PlanRequest JSON), `primary_thread_id` | First line only. `app.cli replay` uses `request` when `--request` is not given. |
| `emit` | `event` (a raw event), `scope` (`"session"` default, or a thread id) | Stamps `id`/`processed_at` when absent, appends to the scope's history, applies its side effects, delivers to the open streams of `scope`. The thread scope must exist (a prior `session.thread_created`) and not be archived. |
| `await` | `match` (subset of a sent payload), `count` (default 1) | Blocks until the backend sends; each consumed send must contain `match` (recursive subset: dict keys, lists element-wise with equal length, booleans never equal integers): `{"type": "user.custom_tool_result", "custom_tool_use_id": "sevt_...", "is_error": true}`. |
| `await_call` | `method` (a Protocol method), `count` | Blocks until that method has **succeeded** once more than earlier `await_call` steps consumed, e.g. `update_budget` before the session resumes. |
| `await_stream` | `scope` (default `"session"`) | Blocks until a stream of that scope is open: the backend opened the thread stream after `session.thread_created`, or reconnected after a `disconnect`. |
| `usage` | `list_cost_cents`, `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation`, `web_search_requests`, `web_fetch_requests`, `active_seconds`, optional `id`/`processed_at` | Emits a `session.usage` event carrying them (`list_cost: {"amount": "<cents>", "currency": "USD"}`, plus the session's `budget`), which updates the tracked usage. The real API emits one before every idle. |
| `set` | `status`, `status_lag`, `budget_cents`, `list_cost_cents`, `page_size` | Changes tracked state without emitting. |
| `disconnect` | `scope` (default `"session"`, or `"all"`), `error_type` | Makes the open stream(s) of `scope` raise `StreamDisconnectedError` (a network drop, or with `error_type` an `event: error` SSE message such as `overloaded_error`). |
| `fail_next` | `method`, `error` (`api_unavailable`, `api_rejected`, `not_found`, `busy`, `disconnected`, `hang`), `after` (default 0), `message` | Like `fail_next()` from Python. |
| `checkpoint` | `name` | Blocks until the test calls `release(name)` (a release before arrival also counts); `await fake.reached(name)` returns once the driver gets here. Used to stop a consumer mid-plan, or to time a user action. |

`{"$fixture": "<path>"}` as a value is replaced by the JSON file at
`backend/tests/fixtures/<path>`, so a full Plan doesn't have to fit on one line:
`{"op": "emit", "event": {"id": "sevt_1", "type": "agent.custom_tool_use", "name": "submit_plan", "input": {"$fixture": "ma/plans/lisbon_valid.json"}}}`.

Raw events in scripts are the JSON the API sends (catalog: notes §2g; shapes: the SDK models
under `anthropic/types/beta/sessions/`).

## Recording and inspection

| Attribute | Content |
|---|---|
| `created` | Every `create_session` call (`CreatedSession`: session id, pin, environment, budget, metadata, title). |
| `sent` | Every accepted send (`SentEvent`: session id, the exact payload, `open_streams` at send time). `sent[0].open_streams` containing `"session"` proves step 1 of the consumer. A refused send is not in `sent`. |
| `calls` | Every Protocol call as it starts (`RecordedCall`: method, session id, args, `error` it raised). `calls_of(method)`; `await fake.called(method, count)` waits for one. |
| `budget_updates`, `archived`, `archived_threads`, `deleted`, `closed` | The corresponding successful calls, in order. |
| `history`, `thread_history(tid)` | The scripted session's histories, echoes included (copies). |
| `status`, `session_info()`, `threads()`, `open_streams`, `primary_thread_id` | Tracked state without recording a call or consuming status lag. |
| `meta`, `script`, `done`, `mismatches`, `unmatched_sends`, `at_checkpoint` | The script and the driver's progress. |

Test-side controls: `emit(event, scope=...)` and `disconnect(scope, error_type=...)` act on the
scripted session like the steps of the same name; `fail_next(...)`, `start()`,
`reached(name)`, `release(name)`, `called(method)`, `wait_until_done()`,
`assert_script_done()` and `shutdown()` (cancel the driver of a script left unfinished on
purpose).

## Fault injection

`fail_next(method, error, *, after=0)` makes the next call of a Protocol method raise, after
`after` calls that succeed normally (a backfill that fails on its second page: `page_size=10`
and `fail_next("list_events", "api_unavailable", after=1)`). `error` is a `ManagedAgentsError`
or a kind name: `api_unavailable` (`ApiUnavailableError`, "429/5xx after the SDK's 1 +
`MAX_RETRIES` attempts"), `api_rejected`, `not_found` (`SessionNotFoundError`, the nightly job),
`busy` (`SessionBusyError`, the archive race), `disconnected` (`StreamDisconnectedError`, when
opening a stream), or `hang`: the call blocks until it is cancelled, like a process killed
mid-call. A hang nobody cancels within `await_timeout` becomes a mismatch and the call fails.

`set_latency(method, seconds)` makes every later call of a method wait before it runs (0
removes it), like a slow network: the fake otherwise answers at once, which hides races that a
real client's latency exposes (a thread backfill still in flight when a decision ends the
consumer, `test_consumer_resume.py`). The wait comes before any `fail_next` fault.

## Shipped scenarios

All share one request (Milano -> Lisbona, 2027-04-14..18, 2 adults and children aged 9 and 6,
2800 EUR) and one valid plan (`plans/lisbon_valid.json`; it maps to a Trip that passes
TripTracker's trip.json). Subagents run on their own threads: `session.thread_created` plus
`agent.thread_message_sent` on the session stream, then on the thread
`session.thread_status_running` (cross-posted copy with another id on the session stream),
`agent.thread_message_received`, tool activity (`web_search`, `web_fetch`, Expedia MCP
`search_flights`/`search_hotels`, `bash` running `build_link.py`), a `write` of
`/workspace/results/<agent>.json.tmp` (a valid results envelope) and a `bash` `mv` to the final
name, an Italian `agent.message`, the report (`agent.thread_message_sent` on the thread,
`agent.thread_message_received` on the session stream) and `session.thread_status_idle`
(cross-posted). User-facing agent text is Italian; inter-agent messages are English.
`test_fixture_shapes.py` keeps them in line with the SDK (see its docstring).

| Scenario | How a test drives it | Proves |
|---|---|---|
| `happy_path` | Run the consumer. | Stream open before the first message; thread streams opened on `thread_created` (`await_stream`) and backfilled (the transport thread's first events predate its stream); a flights MCP call cross-posted to the session stream with `session_thread_id`; a second wave for activities; UI events with growing `seq`; `submit_plan` accepted; `end_turn` -> `ready`; with status lag 1, archived after the status poll. |
| `rejected_then_accepted` | Run the consumer. | `is_error` round trip with the validation errors (`book_by == scheduled_for`, unknown `stop_ref`); `submit_attempts == 2`; `ready`. |
| `three_rejections_failed` | Run the consumer, then `wait_until_done()`. | Third rejection -> `failed`, `user.interrupt` sent after the third answer, no fourth evaluation; the post-interrupt idle reaches the history only. |
| `budget_reached` | Run the consumer to `budget_paused`; "Continua" (`update_budget(max(cap, consumed) + 200)`); start the resumed consumer. | `budget_reached` (session and lodging thread) -> `budget_paused`; the update emits `session.updated`; the session resumes by itself [INFERRED, P9]; a `user.message` is refused while at the budget; no re-acting on the old idle; `ready`. |
| `requires_action_blocked` | Run the consumer. | An MCP permission ask (`evaluated_permission: ask`) idles thread and session with `requires_action` on that call -> `blocked`, session kept. |
| `end_turn_without_plan` | Run the consumer. | An MCP error result, then `end_turn` without `submit_plan` -> `failed` with the Italian reason. |
| `mcp_failure` | Run the consumer. | `session.error` `mcp_connection_failed_error` (`retrying`, then `exhausted`) only logged; the Kiwi call ends with an error result; the run goes on; `ready` (the plan carries a Kiwi warning). |
| `restart_resume` | `reached("crash")`, `called("send_custom_tool_result")`, stop the consumer, start a resumed one, `release("crash")`. Optionally `page_size=10` and `fail_next("list_events", ..., after=1)` before the resume. | Consumer 1 stores the `submit_plan` outcome but its answer hangs (a scripted `hang`); the resumed consumer lists the history (nothing stored twice, `ma_event_id` unique) and answers the unanswered call from the stored outcome; events after the crash carry `+02:00` offsets (parse, never compare strings); `ready`. |
| `interrupt` | `reached("working")`, request the interrupt (it sends `user.interrupt`), `release("working")`. | Threads and session idle with `end_turn` after the interrupt -> `interrupted`, archived; the echo's empty id is stored once under its synthetic key. Stop the consumer before `release` for the "interrupt then restart" case. |
| `unknown_event_type` | Run the consumer. | `session.checkpoint_created` (session) and `agent.tool_progress` (thread), unknown to the SDK, become generic events, never exceptions; `ready`. |
| `stream_error_event` | Run the consumer (it must reconnect). | `event: error` `overloaded_error` mid-run: `StreamDisconnectedError(error_type=...)`, events emitted while down come from the history, no loss or duplicates; `ready`. |
| `redelegation` | Run the consumer. | Two `session.thread_created` for `activities`; the older thread, idle with `end_turn`, is superseded (`archived_threads`) [INFERRED, P6]; `ready`. |
| `accepted_then_budget_reached` | Run the consumer. | `submit_plan` accepted, then `budget_reached`: `ready` and archived, never `budget_paused`. |
| `rescheduled_and_errors` | Run the consumer. | `session.status_rescheduled` and a `retrying` `session.error` only logged; a `terminal` `session.error` and `session.status_terminated` (streams end normally) -> `failed`. |

Usage tracking (`session.usage` -> `plans.cost_cents` and the events' `cost_cents`) is in every
scenario: one `usage` step before each idle. A stream drop without `error_type` is
`fake.disconnect()` from the test at any point of any scenario.

`tests/test_fake_client.py` plays every scenario with a minimal reference consumer, so a
scenario that can't be completed by a consumer following the documented protocol fails there
first. `app.cli replay` can play every scenario without a checkpoint or `await_call`;
`restart_resume`, `interrupt` and `budget_reached` need a test (or the CLI) to act at those
steps, else they end in a timeout mismatch.

## Not the fake's job

The fake never parses SSE or HTTP. These belong to `SdkManagedAgentsClient` and its tests
(`test_ma_client.py`), which build the real SDK client on the SDK's own HTTP library:

```python
sdk = AsyncAnthropic(
    api_key="test",
    base_url="http://ma.test",
    max_retries=MAX_RETRIES,
    http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
)
```

`anthropic==1.13.0` uses `httpx2`: an `httpx.AsyncClient` raises TypeError, and **respx never
intercepts SDK traffic** (it patches `httpx` only). A test that "mocks" the Anthropic API with
respx would send real requests; `tests/conftest.py` points `ANTHROPIC_BASE_URL` at a dead local
port and blanks every credential variable, so such a mistake fails fast instead. respx is for
the backend's own `httpx` code: fx, auth, triptracker_schema.

Cases `test_ma_client.py` must cover with synthetic SSE bodies: `event: ping` and an empty
`data:` (skipped); `event: error` with `overloaded_error` (`StreamDisconnectedError` with
`error_type`); a `data:` without `event:` line and a payload without `type` (type taken from
the event name; dispatch on `data["type"]`); `session.usage` and an unknown type (yielded); a
body that raises `httpx2.ReadError` after one event (`StreamDisconnectedError`); listings read
from the raw body (no added nulls, timestamps untouched); 408/409/429/5xx after the retries
(`ApiUnavailableError`, 1 + `MAX_RETRIES` attempts), 404, other 4xx; archive/delete answered
400/409 (`SessionBusyError` after exactly one attempt); a `retry-after` far beyond
`CALL_DEADLINE_SECONDS` (`ApiUnavailableError` at the deadline).
