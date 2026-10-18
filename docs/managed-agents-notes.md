# Managed Agents API notes for trip-planner

Researched 2026-10-12. **Offline only:** I made no Anthropic API call, created no Managed Agents session and contacted no travel MCP server. Everything here comes from four sources:

1. The installed Python SDK, `anthropic==1.13.0`.
2. The bundled `claude-api` skill, version 2.1.286.
3. The official docs on platform.claude.com, fetched 2026-10-12.
4. The public source and README of the official `ant` CLI repository on GitHub. I only read them; I didn't install or run the CLI.

Several request shapes were also checked offline against the SDK with an `httpx2.MockTransport` that never touches the network.

## Tag legend

Every statement carries one of these tags:

| Tag | Meaning |
|---|---|
| `[SDK <path>]` | Read from the SDK source. `<path>` is relative to `$SDK` (defined below). |
| `[SDK <path>; offline]` | Also confirmed offline by sending the request through a mock transport and inspecting it. |
| `[DOCS <url>]` | Official documentation, fetched 2026-10-12. GitHub URLs of the official `anthropics/anthropic-cli` repository also count as DOCS. |
| `[SKILL <file>]` | `claude-api` skill v2.1.286. Paths are under `.../bundled-skills/2.1.286/<hash>/claude-api/`. |
| `[INFERRED]` | My own reasoning. Not verified, so never treat it as fact. |
| `[PROBE Pn <report>]` | Measured live by `scripts/probe_session.py` (§4); the report in `docs/probes/` holds the event sequence. One run, so one observation. |

**Where the SDK lives:**

```
$SDK = /Users/michb/.cache/uv/archive-v0/IOkgSndR97g4pDjSQlI3Y/lib/python3.13/site-packages/anthropic
```

To print the path again:

```
uv run --no-project --with anthropic==1.13.0 python -c "import anthropic,os;print(os.path.dirname(anthropic.__file__))"
```

**When sources disagree:** SDK first, then skill, then docs, as the task specified. The one exception is runtime behaviour the SDK can't describe (for example network filtering). There the current docs page wins over the cached skill, and the conflict is listed in §3.

---

## 1. Summary: spec items to verify on day 1

Spec line numbers refer to `docs/spec/implementation-doc.it.md`.

### 1a. Items the spec explicitly marks "da verificare il giorno 1"

| # | Spec item (line) | Verdict | Evidence |
|---|---|---|---|
| D1 | Can a custom tool's `input_schema` be a file reference (`input_schema: { $ref: schema/plan.json }`), or must it be pasted inline? (l.181, l.227) | **contradicted** | **API:** `input_schema` must be an inline JSON Schema object with required `type: "object"` [SDK types/beta/beta_managed_agents_custom_tool_input_schema_param.py]. The API can't resolve a reference to a local file [INFERRED].<br>**`ant apply`:** has no `$ref` for `input_schema`. It does let you include a *whole tool object* from a data file in the `tools` list (`- ./tools/submit_plan.json`, ".yml/.yaml/.json") [DOCS https://github.com/anthropics/anthropic-cli/blob/main/README.md] [DOCS https://github.com/anthropics/anthropic-cli/blob/main/internal/declarative/core/include.go]. |
| D2 | The exact syntax `ant apply` uses to substitute IDs from the lockfile (`$AGENT_FLIGHTS`, `$SKILL_TRIP_TRACKER_SCHEMA`). (l.184-193, l.228) | **contradicted** | `ant apply` has **no** variable substitution. Wherever the API expects an ID, you write the **relative path** to the other resource's file. `ant apply` creates resources in dependency order, fills in the real IDs and **pins the version** [DOCS https://platform.claude.com/docs/en/cli-sdks-libraries/cli/apply].<br>Path references are supported in `skills`, `multiagent.agents`, `multiagent.subagents.predefined_agents` and `multiagent.workflows.predefined_agents` [DOCS https://github.com/anthropics/anthropic-cli/blob/main/internal/declarative/claude/kinds.go].<br>An object like `{type: agent, id: $AGENT_FLIGHTS}` has no `path` key, so it is passed through **verbatim**: the literal string `$AGENT_FLIGHTS` is sent to the API [DOCS https://github.com/anthropics/anthropic-cli/blob/main/internal/declarative/core/refs.go].<br>The docs do show `$REVIEWER_AGENT_ID` in one example, but that is shell heredoc expansion done before the file is written, not an `ant` feature [DOCS https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration]. |
| D3 | Exact MCP tool names, read on day 1 with a `tools/list` from a probe session. (l.247-248) | **needs_live_probe** | `mcp_toolset.configs[].name` is "the bare tool name as reported by the server" [DOCS https://platform.claude.com/docs/en/managed-agents/mcp-connector]. The SDK has no endpoint that lists an MCP server's tools [SDK resources/beta/agents/agents.py] [INFERRED]. Probe step P4. |
| D4 | Do `web_search` and `web_fetch` go through the sandbox network filter, or are they exempt? (l.256-257) | **contradicted** (spec risk table rates it "bassa"; it is the documented behaviour) | With `limited` networking, the environment's `allowed_hosts` **also applies** to `web_search` and `web_fetch`:<br>- `web_fetch` to a host that isn't listed gets a `url_not_allowed` error.<br>- `web_search` silently omits results from unlisted hosts.<br>- `allow_mcp_servers` and `allow_package_managers` add no hosts for these tools.<br>- An empty `allowed_hosts` means no search result or fetched page at all.<br>[DOCS https://platform.claude.com/docs/en/managed-agents/environments] [DOCS https://platform.claude.com/docs/en/managed-agents/tools-web-restrictions]<br>The cached skill says the opposite ("networking does not govern web_search / web_fetch") [SKILL shared/managed-agents-environments.md]. Confirm with probe P5. |
| D5 | Can a subagent write to the coordinator or to another subagent while it works? (`send_to_agent`, `list_agents`) (l.311-313, l.1252) | **needs_live_probe** (partly answered) | - **Coordinator:** gets `list_agents` and `send_to_agent` [SKILL shared/managed-agents-multiagent.md].<br>- **Subagent → coordinator:** documented. On the primary thread, `agent.thread_message_received` means "a subagent sent the primary thread's agent a report or question" [DOCS https://platform.claude.com/docs/en/managed-agents/session-threads].<br>- **End-of-turn report:** sent automatically. An *interrupted* child does not send it [DOCS same page].<br>- **Subagent → sibling:** not documented anywhere.<br>- **Tool names:** neither tool name appears in the SDK [SDK `grep -r send_to_agent $SDK` → no hits].<br>Probe step P6. |
| D6 | Expedia/Kiwi/lastminute MCP accept connections from a Managed Agents session (the main project risk). (l.1280-1281) | **needs_live_probe** | Session creation does **not** validate MCP connectivity. Failures arrive as `session.error` with `mcp_connection_failed_error` or `mcp_authentication_failed_error`, plus `retry_status` [DOCS https://platform.claude.com/docs/en/managed-agents/mcp-connector] [SDK types/beta/sessions/beta_managed_agents_mcp_connection_failed_error.py]. If no vault credential matches, the connection is attempted unauthenticated [DOCS mcp-connector]. Probe step P4. |
| D7 | Booking-site URL templates (l.359) | needs_live_probe | Not Managed Agents. Owned by the `booking-links` skill task; listed only for completeness. |
| D8 | Bank of Italy endpoint for exchange rates (l.533) | needs_live_probe | Not Managed Agents. Owned by the `fx.py` task; listed only for completeness. |

### 1b. Implicit Managed Agents assumptions in the spec

| # | Spec assumption (line) | Verdict | Evidence |
|---|---|---|---|
| I1 | "lo stream consegna solo gli eventi emessi dopo l'apertura" (l.616-617) | **confirmed** | "A stream delivers only the events emitted after it opens" [DOCS https://platform.claude.com/docs/en/managed-agents/events-and-streaming]. The SDK's own runner opens the stream *before* listing history for exactly this reason [SDK lib/tools/_beta_session_runner.py:660-666]. |
| I2 | Thread stream at `/v1/sessions/{id}/threads/{thread_id}/stream` (l.618-619) | **confirmed** | `client.beta.sessions.threads.events.stream(thread_id, session_id=...)` → `GET /v1/sessions/{session_id}/threads/{thread_id}/stream` [SDK resources/beta/sessions/threads/events.py:126-191; offline]. |
| I3 | On the main stream, subagents show only start, end and messages; their tool calls go through the threads (l.619-620) | **confirmed, with one nuance** | The primary stream is "a condensed view… start and end of their work, and blocking events such as tool permission requests" [DOCS https://platform.claude.com/docs/en/managed-agents/session-threads]. **Nuance:** a subagent's blocking calls (permission asks, `agent.custom_tool_use`) are cross-posted to the primary stream with `session_thread_id` [SDK types/beta/sessions/beta_managed_agents_agent_custom_tool_use_event.py]. |
| I4 | Resume = open the stream, list the history, skip events already seen by `id` (l.632-634) | **confirmed, with caveats** | Documented pattern [DOCS events-and-streaming §Reconnect without missing events]. Caveats in §2f: thread histories, cross-posted copies with different ids, interrupts with an empty id. |
| I5 | `budget.max_list_cost` = `"400"` (= $4) in production and `"60"` in development (l.883) | **confirmed; the shape needs correcting** | The amount is US cents written as a string, so `"400"` = $4.00 and `"60"` = $0.60. The full shape is `budget={"type": "limit", "max_list_cost": {"amount": "400", "currency": "USD"}}` [SDK types/beta/beta_managed_agents_budget_limit_param.py] [SDK types/beta_monetary_amount_param.py] [DOCS https://platform.claude.com/docs/en/managed-agents/budgets]. |
| I6 | `stop_reason` values `end_turn`, `budget_reached`, `requires_action` (l.628-631, l.884) | **confirmed** (two more exist) | The SDK union also has `retries_exhausted` and `refusal` [SDK types/beta/sessions/beta_managed_agents_session_status_idle_event.py]. |
| I7 | `session.status_rescheduled`: log it and wait, the platform retries (l.1225) | **confirmed** | "Indicates the session is recovering from an error state and is rescheduled" [SDK types/beta/sessions/beta_managed_agents_session_status_rescheduled_event.py]. "Transient error occurred, retrying automatically" [DOCS https://platform.claude.com/docs/en/managed-agents/session-operations]. |
| I8 | Real costs come from `session.usage` (l.880) | **confirmed, with an SDK caveat** | `session.usage` events and `session.usage.list_cost` exist [SDK types/beta/beta_managed_agents_session_usage_event.py] [SDK types/beta/beta_managed_agents_session_usage.py]. **Caveat:** the 1.13.0 SSE iterator silently **drops** `session.usage` (§2f). |
| I9 | `user.define_outcome` exists (l.1099) | **confirmed** | [SDK types/beta/sessions/beta_managed_agents_user_define_outcome_event_params.py] |
| I10 | `multiagent_20261001` with `subagents.{inline_agents, predefined_agents}` and `workflows` (l.186-225) | **confirmed** | [SDK types/beta/beta_managed_agents_multiagent20261001_params.py] [DOCS https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration] |
| I11 | Delegation is one level only (l.115, l.264) | **confirmed** | "Referencing another agent that has `multiagent` set fails … with a 400" [DOCS multiagent-orchestration]. |
| I12 | Every `ant apply` creates a new version; old versions stay available (l.1061-1062, l.1096-1097) | **confirmed for agents and skills** | `ant apply` only updates resources that changed. Each agent update creates a new immutable integer version [SDK types/beta/beta_managed_agents_agent.py "version… increments when the agent is modified"]. Past versions are listable: `client.beta.agents.versions.list` [SDK resources/beta/agents/versions.py]. **Environments are not versioned** [DOCS environments]. |
| I13 | Production pins each subagent's and skill's version; development "always uses the latest" (l.1087-1088) | **partly contradicted** | `predefined_agents` entries are *always* pinned, to the version current when the coordinator is created or updated. An omitted `version` means "latest **at save time**", not "latest at session time" [DOCS multiagent-orchestration §Pinning]. So development must re-save the coordinator whenever a subagent changes; `ant apply` does this automatically [DOCS anthropic-cli README "References record a specific version"]. Skill `version: latest` behaviour: see P11. |
| I14 | `claude-haiku-5-5` exists (development profile, l.258) | **confirmed** | It is the first literal in `BetaManagedAgentsModel` [SDK types/beta/beta_managed_agents_model.py]. Used in the official multiagent example [DOCS multiagent-orchestration]. Priced at $0.10/$0.50 per MTok for prompts ≤100k tokens [DOCS https://platform.claude.com/docs/en/about-claude/pricing]. |
| I15 | MCP needs `permission_policy: always_allow`, otherwise every call stops for confirmation (l.244-247) | **confirmed** | "The MCP toolset defaults to a permission policy of `always_ask`" [DOCS mcp-connector]. |
| I16 | `networking: limited`, `allow_mcp_servers: true`, `allowed_hosts` for Photon and Open-Meteo (l.254-255) | **shape confirmed; consequence contradicted** | Fields confirmed [SDK types/beta/beta_limited_network_params.py; offline]. **But see D4:** with only those two hosts, `web_search` and `web_fetch` return almost nothing. |
| I17 | Sessions are not covered by Zero Data Retention (l.944-946) | **confirmed** | "not currently eligible for Zero Data Retention" [DOCS https://platform.claude.com/docs/en/managed-agents/overview]. |
| I18 | Runtime $0.08/hour, search $10 per 1,000, no batch discount (l.881, l.905-909) | **confirmed** | [DOCS budgets §How list cost is measured] [DOCS pricing §Claude Managed Agents pricing] |
| I19 | 429/5xx retried with exponential backoff and jitter, max 5 attempts (l.1226-1227) | **confirmed as configurable** | The SDK default is **2** retries. `max_retries` counts retries *after* the first attempt (`for retries_taken in range(max_retries + 1)` [SDK _base_client.py:1159]; offline: `max_retries=5` made 6 HTTP attempts), so "at most 5 attempts" is `max_retries=4` (§2j) [SDK _constants.py] [SDK _base_client.py:863-896]. |
| I20 | `ant apply` records IDs in `claude-lock.json`, which is committed (l.165, l.1089) | **confirmed** | Format in §2h [DOCS cli/apply]. |
| I21 | Two profiles with separate keys, "due set di agenti con ID distinti nel lockfile" (l.259-261, l.1161) | **needs_live_probe** (design caveat) | A lockfile is bound to one organization and workspace. `ant apply` "refuses a lockfile whose organization or workspace doesn't match your credentials". Keep one lockfile per workspace with `--lock-file` [DOCS cli/apply §Flags]. If the dev and prod keys live in different workspaces, a single lockfile can't hold both. §2h has a layout. |
| I22 | Skills are uploaded with `ant apply skills/<name>` (l.347) | **confirmed** | Example: `ant apply skills/pr-summary` [DOCS https://platform.claude.com/docs/en/managed-agents/skills]. |
| I23 | `POST /plans/{id}/interrupt` sends `user.interrupt` (l.643) | **confirmed** | [SDK types/beta/sessions/beta_managed_agents_user_interrupt_event_params.py; offline] |
| I24 | Archive the session when the plan is ready; delete sessions after 90 days (l.629, l.947-949, l.1220) | **confirmed, with a race** | A `running` session can be neither archived nor deleted [DOCS session-operations]. The `session.status_idle` event arrives slightly before the queryable status flips, so poll before archiving (§2d) [SKILL shared/managed-agents-client-patterns.md §6]. |

---

## 2. Reference by topic (a-j)

### a. Agents

#### Methods

All agent calls go to `client.beta.agents.*`. The SDK automatically adds the header `anthropic-beta: managed-agents-2026-04-01` and the query string `?beta=true` [SDK resources/beta/agents/agents.py:136-149; offline].

| Method | HTTP call |
|---|---|
| `create(...)` | `POST /v1/agents` |
| `retrieve(agent_id, version=N?)` | `GET /v1/agents/{id}` |
| `update(agent_id, version=current?, ...)` | `POST /v1/agents/{id}` |
| `list(include_archived?, limit≤100, page?)` | `GET /v1/agents` |
| `archive(agent_id)` | `POST /v1/agents/{id}/archive` |
| `versions.list(agent_id, limit≤100, page?)` | `GET /v1/agents/{id}/versions` |

There is **no delete** for agents [SDK resources/beta/agents/agents.py] [SKILL shared/managed-agents-api-reference.md]. Archiving is permanent: no unarchive, and new sessions can't reference an archived agent [DOCS https://platform.claude.com/docs/en/managed-agents/overview] [SKILL shared/managed-agents-overview.md].

#### Create parameters

Source: [SDK types/beta/agent_create_params.py].

| Field | Shape and limits |
|---|---|
| `name` | Required. |
| `model` | Required. A model string, or `{id, effort?, inference_geo?, speed?}`. `effort` is one of `low`, `medium`, `high`, `xhigh`, `max`, or `{type: "<level>"}`. Omitting it uses the model's default [SDK types/beta/beta_managed_agents_model_config_params.py]. The Opus 5.5 default is `medium` [SKILL SKILL.md]. |
| `system` | Optional string, up to 100,000 characters [SDK types/beta/beta_managed_agents_agent_with_overrides_params.py]. |
| `description` | Optional. |
| `tools` | Optional. "Maximum of 256 tools across all toolsets." The skill says 128 (§3). |
| `mcp_servers` | Optional. Max 20, unique names. **Every server must be referenced by an `mcp_toolset` in `tools`**, otherwise the request is rejected. |
| `skills` | Optional. |
| `multiagent` | Optional. |
| `metadata` | Optional. Max 16 pairs; keys up to 64 chars, values up to 512 chars. |

#### Versions

- `version` is an int that starts at 1 and increments on every modification [SDK types/beta/beta_managed_agents_agent.py].
- `update(..., version=N)` is optimistic concurrency: the request fails (409) if `N` isn't the current version. Omit it for last-write-wins [SDK types/beta/agent_update_params.py] [SKILL shared/managed-agents-core.md §Versioning].
- Array fields (`tools`, `mcp_servers`, `skills`) are fully replaced on update [SDK types/beta/agent_update_params.py].
- `multiagent` on update: **the SDK contradicts itself.** The params type says a `multiagent_20261001` object is **merged level by level** with the stored value (omitted keys keep their stored value, a key sent as `null` takes its *default*, so `"workflows": null` *enables* workflows; a sent `predefined_agents` list replaces the stored list) [SDK types/beta/beta_managed_agents_multiagent20261001_params.py:16]. The update method and its params say "Full replacement. Omit to preserve; send null to clear" [SDK types/beta/agent_update_params.py:49-53] [SDK resources/beta/agents/agents.py:282]. **Always send the complete object** (`type`, `subagents` with `inline_agents` and `predefined_agents`, `workflows: {type: disabled}`, `advisor`), never `null` for a sub-key, so both readings give the same result; probe P12 retrieves after an update and diffs (§3, "Source conflicts").
- **Pinning a session to a version:** `sessions.create(agent={"type": "agent", "id": ..., "version": N})`. A bare id string means the latest version at session creation [SDK types/beta/session_create_params.py].

#### Built-in toolset: `agent_toolset_20260401`

Shape:

```
{type: "agent_toolset_20260401",
 default_config?: {enabled?: bool, permission_policy?},
 configs?: [...]}
```

[SDK types/beta/beta_managed_agents_agent_toolset20260401_params.py]

- **Tool names in `configs`:** `bash`, `edit`, `read`, `write`, `glob`, `grep`, `web_fetch`, `web_search` [SDK types/beta/beta_managed_agents_agent_tool_config_params.py].
- **Each `configs` entry:** `{name, enabled?, permission_policy?, type?}`. `type` is optional in requests; the server infers it from `name` [DOCS https://platform.claude.com/docs/en/managed-agents/tools].
- **`web_search` and `web_fetch` entries** also take `allowed_domains` or `blocked_domains` (never both, 1-64 plain hostnames). `web_fetch` also takes `max_content_tokens` and `url_sources`; `web_search` also takes `user_location` [SDK types/beta/beta_managed_agents_web_fetch_tool_config_params.py] [SDK types/beta/beta_managed_agents_web_search_tool_config_params.py].
- **`default_config.enabled`** defaults to true when unspecified [SDK types/beta/beta_managed_agents_agent_toolset_default_config_params.py].
- **Permission policies:** `{type: "always_allow"}`, `{type: "always_ask"}` or `{type: "auto"}` [SDK types/beta/beta_managed_agents_always_allow_policy_param.py]. The agent toolset defaults to `always_allow` [DOCS environments §Risks of unrestricted networking].

#### Custom tools

Shape:

```
{type: "custom", name, description, input_schema}
```

[SDK types/beta/beta_managed_agents_custom_tool_params.py]

- **`name`:** 1-128 characters (letters, digits, `_`, `-`). It can't start with `mcp__` or `ant__`, and can't equal a built-in tool name [DOCS tools].
- **`input_schema`:** required `type: "object"`, optional `properties` and `required`. Any other JSON Schema key is accepted (`extra_items=object`) [SDK types/beta/beta_managed_agents_custom_tool_input_schema_param.py].
- **No `strict` field** on Managed Agents custom tools [SDK types/beta/beta_managed_agents_custom_tool_params.py].

**Which JSON Schema features are accepted?** Not documented for Managed Agents custom tools. The documented subset for strict tools and structured outputs is:

- Supported: internal `$ref`, `$defs`, `definitions`, `anyOf`/`allOf`, `enum`, `const`, `default`, and the formats `date-time`, `date`, `uri` and others.
- Not supported: external `$ref`, `minimum`, `maximum`, `exclusiveMinimum`, `minLength`, `maxLength`, and recursive schemas.

[DOCS https://platform.claude.com/docs/en/build-with-claude/structured-outputs]

Non-strict tool schemas are generally passed to the model as-is [INFERRED]. Whether Managed Agents rejects `$defs`/`$ref` must be probed (P2).

**Safest choice:** dereference Pydantic's `$defs` into one self-contained object schema with `type: "object"` at the root [INFERRED]. `anthropic.transform_schema(Plan)` exists, but it is for *strict* schemas: it strips `maxLength`, `pattern` stays, and so on. It is optional here [SDK lib/_parse/_transform.py].

#### MCP servers

Server entry:

```
{type: "url", name (1-255 chars), url}
```

[SDK types/beta/beta_managed_agents_url_mcp_server_params.py]

Toolset entry:

```
{type: "mcp_toolset", mcp_server_name,
 default_config?: {enabled?, permission_policy?},
 configs?: [{name, enabled?, permission_policy?}]}
```

[SDK types/beta/beta_managed_agents_mcp_toolset_params.py]

- MCP `configs` entries take **only** `name`, `enabled` and `permission_policy`. `name` is the bare tool name from the server [DOCS mcp-connector].
- Default policy is `always_ask` [DOCS mcp-connector].
- Authentication goes through vaults (`vault_ids` on the session). With no matching credential, the connection is attempted unauthenticated [DOCS mcp-connector].

#### Skills on an agent

```
{type: "custom", skill_id: "skill_...", version?: "<version id>" | "latest"}
{type: "anthropic", skill_id: "xlsx", version?}
```

[SDK types/beta/beta_managed_agents_custom_skill_params.py]

- `version` is a **string**. Omitting it means latest.
- Custom-skill version ids look like `skver_...` [DOCS https://platform.claude.com/docs/en/build-with-claude/skills-guide].
- The response echoes the resolved `version: str` [SDK types/beta/beta_managed_agents_custom_skill.py].
- Skills need the `read` tool. Clearing `tools` while skills are set returns a 400 [SKILL shared/managed-agents-core.md §Override].
- Skill limit per session: up to 500 skills, deduplicated across all agents in the session [DOCS skills]. The skill says 20 per agent [SKILL shared/managed-agents-core.md].

#### Multiagent

`multiagent` is a union of `coordinator` (legacy) and `multiagent_20261001` [SDK types/beta/beta_managed_agents_multiagent_params.py]. For `multiagent_20261001` [SDK types/beta/beta_managed_agents_multiagent20261001_params.py] [DOCS multiagent-orchestration]:

**`subagents`**

- `{type: "enabled", inline_agents?: {type: "enabled"|"disabled"}, predefined_agents?: [...]}`, or `{type: "disabled"}`.
- Defaults: enabled, with `inline_agents` enabled.
- With inline agents disabled, `predefined_agents` must list at least one agent, otherwise 400.

**`predefined_agents` entries**

- `"agent_id"`, or `{type: "agent", id, version?}`, or `{type: "self"}`.
- At most 20 entries.
- Pinned to the resolved version at coordinator save time. A later subagent update needs a coordinator update before it takes effect.

**`workflows`**

- Same shape as `subagents`. Enabled by default. The spec sets `{type: "disabled"}`.

**`advisor`**

- `{type: "enabled", model}` or `{type: "disabled"}`. Disabled by default.

**Limits**

- One level of delegation: a listed agent can't itself have `multiagent`.
- At most 25 child threads at a time, idle threads included until archived. A thread is archived with `client.beta.sessions.threads.archive(thread_id, session_id=sid)` → `POST /v1/sessions/{sid}/threads/{tid}/archive`, returning the thread with `archived_at` set [SDK resources/beta/sessions/threads/threads.py:201-264, 434-497] [SDK types/beta/sessions/beta_managed_agents_session_thread.py:36-37; offline]. Whether a re-delegation to the same agent reuses its thread or opens a new one is unverified (probe P6). With 4 subagents and at most 2 follow-ups each, this roster stays far below 25 either way; the backend archives only an idle thread superseded by a newer thread of the same agent [INFERRED].
- Inference geo must be the same across the roster.

[DOCS multiagent-orchestration] [DOCS session-threads]

#### Minimal Python: coordinator

Placeholders (`AGENT_*_ID`, `SKILL_*`, `PLAN_INPUT_SCHEMA`) come from the bootstrap step or the lockfile.

```python
import anthropic

client = anthropic.Anthropic(max_retries=4)  # 1 attempt + 4 retries = the spec's 5 attempts

coordinator = client.beta.agents.create(
    name="coordinator",
    model={"id": "claude-opus-5-5", "effort": "high"},
    system=COORDINATOR_SYSTEM_PROMPT,
    tools=[
        {
            "type": "agent_toolset_20260401",
            "default_config": {"enabled": False},
            "configs": [{"name": n, "enabled": True} for n in ("read", "write", "glob")],
        },
        {
            "type": "custom",
            "name": "submit_plan",
            "description": "Submit the final, validated plan. Call it once, after research is complete.",
            "input_schema": PLAN_INPUT_SCHEMA,  # inline dict, root {"type": "object", ...}
        },
    ],
    skills=[
        {"type": "custom", "skill_id": SKILL_TRIP_TRACKER_SCHEMA, "version": SKILL_TRIP_TRACKER_SCHEMA_VERSION},
        {"type": "custom", "skill_id": SKILL_TRAVEL_RESEARCH_RULES, "version": SKILL_TRAVEL_RESEARCH_RULES_VERSION},
    ],
    multiagent={
        "type": "multiagent_20261001",
        "subagents": {
            "type": "enabled",
            "inline_agents": {"type": "disabled"},
            "predefined_agents": [
                {"type": "agent", "id": AGENT_FLIGHTS_ID, "version": AGENT_FLIGHTS_VERSION},
                # ... lodging, activities, transport
            ],
        },
        "workflows": {"type": "disabled"},
        "advisor": {"type": "disabled"},  # always the complete object (§2a "Versions")
    },
)
print(coordinator.id, coordinator.version)
```

The request body was checked offline against the SDK [SDK resources/beta/agents/agents.py; offline].

#### Minimal Python: subagent with MCP

```python
flights = client.beta.agents.create(
    name="flights",
    model="claude-sonnet-5-5",
    system=FLIGHTS_SYSTEM_PROMPT,
    mcp_servers=[
        {"type": "url", "name": "expedia", "url": "https://www.expedia.com/mcp"},
        {"type": "url", "name": "kiwi", "url": "https://mcp.kiwi.com"},
        {"type": "url", "name": "lastminute", "url": "https://mcp.lastminute.com/mcp"},
    ],
    tools=[
        {
            "type": "agent_toolset_20260401",
            "default_config": {"enabled": False},
            "configs": [{"name": n, "enabled": True} for n in ("web_search", "web_fetch", "bash", "read", "write")],
        },
        *[
            {
                "type": "mcp_toolset",
                "mcp_server_name": server,
                "default_config": {"enabled": False, "permission_policy": {"type": "always_allow"}},
                "configs": [{"name": tool, "enabled": True, "permission_policy": {"type": "always_allow"}} for tool in tool_names],
            }
            for server, tool_names in MCP_SEARCH_TOOLS.items()  # names come from probe P4
        ],
    ],
    skills=[{"type": "custom", "skill_id": SKILL_BOOKING_LINKS}, {"type": "custom", "skill_id": SKILL_TRAVEL_RESEARCH_RULES}],
)
```

---

### b. Environments

#### Methods

All environment calls go to `client.beta.environments.*` [SDK resources/beta/environments/environments.py].

| Method | HTTP call |
|---|---|
| `create(name, config?, description?, metadata?, scope?)` | `POST /v1/environments` |
| `retrieve`, `update`, `list` | `GET`/`POST /v1/environments[/{id}]` |
| `delete` | `DELETE /v1/environments/{id}`. Only when no session references the environment [DOCS environments]. Returns `{id, type: "environment_deleted"}`. |
| `archive` | `POST /v1/environments/{id}/archive`. New sessions can no longer use it; existing ones continue. |

- **Names must be unique:** a duplicate name returns 409 [SKILL shared/managed-agents-environments.md]. Use distinct names per profile [INFERRED].
- **No versions:** "Environments are not versioned" [DOCS environments].
- **Updates** apply only to new containers [SKILL shared/managed-agents-environments.md].

#### Cloud config

```
config={"type": "cloud", "networking": {...}, "packages"?: {...}}
```

[SDK types/beta/beta_cloud_config_params.py]

**`networking`** is either `{type: "unrestricted"}` or:

```
{type: "limited",
 allowed_hosts?: [str],
 allow_mcp_servers?: bool (default false),
 allow_package_managers?: bool (default false)}
```

[SDK types/beta/beta_limited_network_params.py]

Notes on `networking`:

- If `networking` is omitted, the environment gets **`unrestricted`**. Always set it explicitly [DOCS environments].
- **`allowed_hosts` format:** a bare hostname matches that exact host only (`example.com` doesn't match `www.example.com`). `*.example.com` matches every subdomain, but not `example.com` itself. No scheme, port or path [DOCS environments].
- **MCP hosts:** if `allow_mcp_servers` is false and an agent (or a listed subagent) declares an MCP host that isn't in `allowed_hosts`, **session creation fails with 400** [DOCS environments] [DOCS mcp-connector].

**`packages`** is `{apt?, cargo?, gem?, go?, npm?, pip?}`. Under `limited` it requires `allow_package_managers: true` [SDK types/beta/beta_packages_params.py].

#### `web_search` / `web_fetch` and the network filter (D4)

Current docs:

> With `limited` networking, `allowed_hosts` also applies to the `web_search` and `web_fetch` tools … `allow_package_managers` and `allow_mcp_servers` add no hosts for these tools. When `allowed_hosts` lists no hosts, no `web_fetch` or `web_search` call returns a page or a search result. A host that you add to `allowed_hosts` for these tools is also open to the sandbox. `unrestricted` networking and self-hosted environments do not limit these tools.

[DOCS environments]

- A session create or update fails with 400 if an enabled web tool's `allowed_domains` contains an entry not within `allowed_hosts` [DOCS tools-web-restrictions].
- The cached skill states the opposite [SKILL shared/managed-agents-environments.md] [SKILL shared/managed-agents-tools.md]. Treat the docs as current and confirm with P5.

#### Minimal Python

```python
env = client.beta.environments.create(
    name="trip-planner-development",
    config={
        "type": "cloud",
        "networking": {
            "type": "limited",
            "allowed_hosts": ["photon.komoot.io", "api.open-meteo.com"],  # plus every site web_search/web_fetch must reach (D4)
            "allow_mcp_servers": True,
        },
    },
)
```

The body was checked offline [SDK resources/beta/environments/environments.py; offline]. The two host names are this project's choice [INFERRED].

---

### c. Skills

#### Two namespaces

Both exist in 1.13.0:

- `client.skills.*` (GA, no beta header, `POST /v1/skills`)
- `client.beta.skills.*` (`POST /v1/skills?beta=true`)

[SDK resources/skills/skills.py] [SDK resources/beta/skills/skills.py; offline]

**Use `client.skills`** (the GA namespace, used in the docs) [DOCS skills].

- If `betas=["skills-2025-10-02"]` is sent, versions are addressed by an epoch-timestamp string instead of a version id [SDK resources/beta/skills/versions.py:139-170].
- Neither namespace adds a Managed Agents beta header. Skills need none [SKILL shared/managed-agents-overview.md].

#### Methods

`client.skills.*`:

| Method | Notes |
|---|---|
| `create(files, display_name?)` | Returns `Skill{id, latest_version_id, display_name, source, ...}`. |
| `versions.create(skill_id, files)` | Creates a new version. |
| `versions.list(skill_id)` | |
| `versions.retrieve(version, skill_id=)` | `version` = a version id or `"latest"`. |
| `versions.delete(version, skill_id=)` | |
| `list`, `retrieve`, `delete` | `delete` only; skills have no archive. |

[SDK resources/skills/versions.py:56-239] [SDK types/beta/beta_skill.py]

**Beta only:** `client.beta.skills.versions.download(...)` returns a zip archive. The GA `client.skills.versions` has no `download` in 1.13.0 (only `create`, `retrieve`, `list`, `delete`) [SDK resources/beta/skills/versions.py:349, 725] [SDK resources/skills/versions.py].

#### Upload format

- **Multipart.** Each file goes in the field `files[]`, with filename `<top-dir>/<relative path>`. All files must sit under one top-level directory with `SKILL.md` at its root [SDK resources/beta/skills/skills.py:69-145; offline: filenames were `booking-links/SKILL.md`, `booking-links/scripts/build_link.py`].
- **`files_from_dir(path)`** builds exactly that list (paths relative to the directory's parent) [SDK lib/_files.py]. It is **unfiltered**: it walks `directory.iterdir()` recursively and uploads every file, `__pycache__/*.pyc`, `.DS_Store`, `.venv/` and other dotfiles included [SDK lib/_files.py:11-25]. Unlike `ant` (next section), it would push junk into the skill and, through the hash, create spurious new versions. Filter the list first (§2h step 4).
- **A zip archive** is also accepted as a single file [DOCS skills].

#### Rules and limits

- Under 30 MB uncompressed [DOCS skills-guide].
- `SKILL.md` frontmatter: `name` up to 64 characters (lowercase, digits, hyphens; no "anthropic" or "claude"); `description` up to 1024 characters [DOCS skills-guide].
- The upload folder must match `name` in `SKILL.md`. `name` is immutable across versions [DOCS https://github.com/anthropics/anthropic-cli/blob/main/internal/declarative/claude/skill.go] [DOCS skills-guide].
- `ant` checks client-side: at most 1000 files, 32 MiB total, 16 MiB per file. It skips dotfiles, `__pycache__`, `.venv`, `node_modules`, `dist`, `build` and symlinks [DOCS anthropic-cli skill.go].
- **A new version is a full snapshot:** omitted files are not carried over [DOCS skills-guide].

#### Minimal Python

```python
from anthropic.lib import files_from_dir

skill = client.skills.create(files=files_from_dir("skills/booking-links"))
print(skill.id, skill.latest_version_id)  # skill_..., skver_...
new_version = client.skills.versions.create(skill.id, files=files_from_dir("skills/booking-links"))
print(new_version.id)
```

`files_from_dir` uploads everything under the directory (see "Upload format"); use it as is only on a clean checkout, and filter it like `ant` in `scripts/bootstrap.py` [INFERRED].

The SDK typing and the multipart request were checked offline [SDK resources/skills/versions.py; offline]. The id prefixes are from [DOCS skills-guide].

---

### d. Sessions

#### Methods

All session calls go to `client.beta.sessions.*` [SDK resources/beta/sessions/sessions.py].

| Method | HTTP call |
|---|---|
| `create` | `POST /v1/sessions` |
| `retrieve` | `GET /v1/sessions/{id}` |
| `update` | `POST /v1/sessions/{id}` |
| `list(agent_id?, agent_version?, created_at_gt/gte/lt/lte?, include_archived?, limit?, order?, page?, statuses?)` | `GET /v1/sessions` |
| `archive` | `POST /v1/sessions/{id}/archive` |
| `delete` | `DELETE /v1/sessions/{id}` |

Sub-resources: `.events`, `.threads` (including `threads.archive`, §2a "Limits"), `.resources`.

**Listing sessions** [SDK resources/beta/sessions/sessions.py:853-940; offline]: `include_archived` defaults to **false** (archived sessions are hidden unless asked); `order` is by `created_at`, default `desc`; `agent_version` applies only together with `agent_id`; `statuses` repeats to match any of several; the result is an auto-paginating `AsyncBidirectionalPageCursor[BetaManagedAgentsSession]`. Each session carries its `metadata` (`plan_id` here) [SDK types/beta/beta_managed_agents_session.py:38]. The nightly job uses `list(created_at_lt=<now - 90 days>, include_archived=True)` to delete sessions whose `plan_id` has no plan row (a crash between `sessions.create` and the commit), so no transcript outlives the retention [INFERRED].

#### Create parameters

Source: [SDK types/beta/session_create_params.py].

| Field | Shape and limits |
|---|---|
| `agent` | Required. `"agent_id"` (latest), or `{type: "agent", id, version}`, or `{type: "agent_with_overrides", id, version?, model?, system?, tools?, mcp_servers?, skills?}`. Overrides apply to the coordinator and its `self` copies only, not to roster agents [SKILL shared/managed-agents-core.md]. |
| `environment_id` | Required. |
| `budget` | Optional, create-only. `{type: "limit", max_list_cost: {amount: "<integer cents>", currency: "USD"}}`. |
| `initial_events` | Optional. Only `user.message` and `user.define_outcome`, max 50. A non-empty list creates the session directly in `running` [SKILL shared/managed-agents-core.md]. |
| `metadata` | Optional. Max 16 pairs; keys up to 64 chars, values up to 512 chars. The skill says 8 keys (§3). |
| `title` | Optional. |
| `resources` | Optional. Files, GitHub repos, memory stores. |
| `vault_ids` | Optional, create-only. |

#### Budget

- `"400"` = $4.00, `"60"` = $0.60. Integer cents as a string, no decimals (`"25.00"` is rejected). `USD` only [SDK types/beta_monetary_amount_param.py] [DOCS budgets].
- **A budget can only be set at create.** It can later be changed (to a value strictly greater than the consumed list cost) or removed with `budget=None`. Removal is one-way [SDK types/beta/session_update_params.py] [DOCS budgets].
- **What list cost includes:** tokens at the served model's list price, $10 per 1,000 web searches, and runtime at $0.08/hour [DOCS budgets].
- **Enforcement:** the budget is checked before each model request, so the final cost can go past the cap by up to one request per running thread [DOCS budgets].
- **At the cap:** only "settle" events are accepted: `user.tool_confirmation`, `user.tool_result`, `user.custom_tool_result`, `user.interrupt`. A `user.message` returns 400. No event resumes the session; only a budget update does [DOCS budgets].
- **One shared budget** across all threads of a multiagent session [DOCS budgets].

The spec's "Continua con 2 $ in più" button maps to:

```python
client.beta.sessions.update(sid, budget={"type": "limit", "max_list_cost": {"amount": str(consumed_cents + 200), "currency": "USD"}})
```

Base `consumed_cents` on `usage.list_cost`, not on the old cap [DOCS budgets §Change the budget].

#### Usage and cost

There **is** a cost field: `session.usage.list_cost` (`{amount, currency}`, rounded to the cent, "Absent until cost tracking is available"). The same object also has [SDK types/beta/beta_managed_agents_session_usage.py]:

| Field | Meaning |
|---|---|
| `input_tokens`, `output_tokens`, `cache_read_input_tokens` | Token totals. |
| `cache_creation.{ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}` | Cache writes by TTL. |
| `server_tool_use.{web_search_requests, web_fetch_requests}` | `web_fetch_requests` always reads 0 [DOCS budgets]. |
| `active_seconds` | The runtime the cost is priced on. Concurrent threads are counted once. |

- **Per thread:** `client.beta.sessions.threads.retrieve(tid, session_id=sid).usage.list_cost`. It is null until the thread's first idle. Per-thread costs **don't add up** to the session total, which also includes runtime [SDK types/beta/sessions/beta_managed_agents_session_thread_usage.py].
- **The `session.usage` event** carries the same snapshot plus a `budget` echo. One is emitted immediately before *every* `session.status_idle` [DOCS budgets §Monitor spend]. The 1.13.0 iterator drops it (§2f).
- **Per model request:** `span.model_request_end.model_usage` has token counts but no cost [SDK types/beta/sessions/beta_managed_agents_span_model_request_end_event.py].
- **No session-level token fallback.** Session usage sums tokens across every thread and model (Opus or Sonnet coordinator, Sonnet or Haiku subagents) with no per-model breakdown [SDK types/beta/beta_managed_agents_session_usage.py:14-44] [SDK types/beta/sessions/beta_managed_agents_session_usage_snapshot.py:14-40], so "tokens × list price" can't be computed from it. A per-thread estimate is possible: for each thread of `threads.list`, `thread.usage` (input, output, cache read, cache creation 5m/1h, all billed) × the list prices of `thread.agent.model` [SDK types/beta/sessions/beta_managed_agents_session_thread.py:30, 62] [SDK types/beta/sessions/beta_managed_agents_session_thread_usage.py:21-23], plus web searches × $0.01, plus session `usage.active_seconds` / 3600 × $0.08 [INFERRED from DOCS pricing]. `thread.usage` is null until the thread's first idle. The backend does **not** do this: it relies on `list_cost` (from `session.usage`, else `sessions.retrieve`), and the Console's organization limit is the last net.

#### Archive and delete

- **Archive** preserves the history but stops new events. The session goes to `terminated`, and the stream shows `session.status_terminated` [DOCS session-operations] [DOCS https://platform.claude.com/docs/en/managed-agents/reference].
- **Delete** permanently removes the record, the events, the sandbox, and any files the session produced. The stream gets `session.deleted` [DOCS session-operations] [SDK types/beta/sessions/beta_managed_agents_session_deleted_event.py].
- **Neither works on a `running` session.** Interrupt first and wait for `idle`. The SDK retries every 409 (lock timeouts), so send archive/delete with `client.with_options(max_retries=0)` after polling the status: a busy 400/409 then comes back at once instead of after the whole retry schedule [SDK _base_client.py:876-884; offline: `max_retries=5` + a 409 made 6 attempts].
- **A session that finished its work is `idle`, not `terminated`** [DOCS session-operations].

#### Minimal Python

```python
import time

session = client.beta.sessions.create(
    agent={"type": "agent", "id": lock.coordinator.id, "version": lock.coordinator.version},
    environment_id=lock.environment.id,
    budget={"type": "limit", "max_list_cost": {"amount": str(settings.session_budget_cents), "currency": "USD"}},
    metadata={"plan_id": str(plan_id), "agent_profile": settings.agent_profile},
    title=f"plan {plan_id}",
)

# Cleanup after end_turn: poll the status first (post-idle race)
for _ in range(10):
    if client.beta.sessions.retrieve(session.id).status != "running":
        client.with_options(max_retries=0).beta.sessions.archive(session.id)  # no 409 retries
        break
    time.sleep(0.2)
```

The create body was checked offline [SDK resources/beta/sessions/sessions.py; offline]. The polling loop follows [SKILL shared/managed-agents-client-patterns.md §6].

---

### e. Sending events

Endpoint: `client.beta.sessions.events.send(session_id, events=[...])` → `POST /v1/sessions/{id}/events`. It returns `{data: [echoed events]}` [SDK resources/beta/sessions/events.py:160-221] [SDK types/beta/sessions/beta_managed_agents_send_session_events.py].

Events are queued and processed in order. `user.interrupt` jumps the queue [SKILL shared/managed-agents-events.md].

| Event | Params | Source |
|---|---|---|
| `user.message` | `{type, content: [text \| image \| document blocks]}` | [SDK types/beta/sessions/beta_managed_agents_user_message_event_params.py] |
| `user.interrupt` | `{type, session_thread_id?}`. No id interrupts **every** non-archived thread, primary included. | [SDK types/beta/sessions/beta_managed_agents_user_interrupt_event_params.py] |
| `user.custom_tool_result` | `{type, custom_tool_use_id, content?: [text \| image \| document \| search_result], is_error?: bool}`. `custom_tool_use_id` = the **`id` of the `agent.custom_tool_use` event** (`sevt_...`). **No** `session_thread_id` parameter; the server routes by id. | [SDK types/beta/sessions/beta_managed_agents_user_custom_tool_result_event_params.py] [SDK types/beta/sessions/beta_managed_agents_agent_custom_tool_use_event.py] |
| `user.tool_confirmation` | `{type, tool_use_id, result: "allow" \| "deny", deny_message?}` | [SDK types/beta/sessions/beta_managed_agents_user_tool_confirmation_event_params.py] |
| `user.define_outcome` | `{type, description, rubric: {type: "text", content} \| {type: "file", file_id}, max_iterations?}`. Default 3, max 20. The echo carries `outcome_id`. | [SDK types/beta/sessions/beta_managed_agents_user_define_outcome_event_params.py] |
| `system.message` | `{type, content: [text]}`. Must be last in the request and follow a user message or tool result. Model-gated. | [SDK types/beta/sessions/beta_managed_agents_system_message_event_params.py] [SKILL shared/managed-agents-events.md] |
| `user.tool_result` | Self-hosted environments only. Not used here. | [SDK types/beta/sessions/beta_managed_agents_user_tool_result_event_params.py] |

**Custom tool result details:**

- You can send the result as soon as `agent.custom_tool_use` arrives; no need to wait for the `requires_action` idle.
- "A second result for the same call is accepted and has no effect", so it is safe to retry.
- [DOCS events-and-streaming §Return a custom tool result]

**Minimal Python** (`submit_plan` handler; bodies checked offline [SDK resources/beta/sessions/events.py; offline]):

```python
if ev.type == "agent.custom_tool_use" and ev.name == "submit_plan":
    errors = validate_plan(ev.input)
    client.beta.sessions.events.send(sid, events=[{
        "type": "user.custom_tool_result",
        "custom_tool_use_id": ev.id,
        "content": [{"type": "text", "text": "Plan accepted." if not errors else "\n".join(errors)}],
        "is_error": bool(errors),
    }])

client.beta.sessions.events.send(sid, events=[{"type": "user.message", "content": [{"type": "text", "text": request_json}]}])
client.beta.sessions.events.send(sid, events=[{"type": "user.interrupt"}])
```

#### A custom tool left waiting (probe P14)

Measured on 2026-10-18 with Haiku 5.5 agents: a coordinator with a stand-in custom tool `ask_traveller` and one predefined worker with `bash` only, which the coordinator gives six `sleep 30` calls just before calling the tool [PROBE P14 docs/probes/2026-10-18.md]. The coordinator delegated and called the tool in the same model request.

- **Subagents keep working during the wait.** While the call waited 242 s for its result, the worker made all six bash calls and eight model requests and went idle at +190 s. The coordinator made no request during the wait.
- **A subagent's report waits for the result, and for the coordinator's first turn on it.** The worker sent its report at +189 s; it reached the coordinator (`agent.thread_message_received`) at +244 s, 2 s after the result. A report does not wake a coordinator that waits on a custom tool. Nor is it delivered with the result: the coordinator first made two requests on the answer (about 2 s), sent the prompt's "ok" to the worker and wrote that the worker was still running its checks and that it was waiting for its report; only then did the report arrive and start a third request [raw SSE log of the run, quoted in the report's last P14 bullet].
- **Statuses.** `session.status_idle` (`requires_action`) came first, then `session.status_running` at once while the delegation ran: the session reads `running` while a subagent works and the primary thread reads `idle`. When the worker went idle the stream carried `session.thread_status_idle` and a `session.usage`, but **no second `session.status_idle`**; `sessions.retrieve` read `idle` from then on. After the result the coordinator's thread went `running` with no `session.status_running`, and the turn ended with `session.status_idle` (`end_turn`).
- **`user.interrupt` works during the wait, and needs no result first.** Sent without a thread id 20 s into the wait (worker running), it was accepted. Within 0.6 s the platform closed the pending call itself with an **`agent.tool_result`** (`tool_use_id` = the `agent.custom_tool_use` id, `is_error: true`, text "Tool execution was interrupted before completion. Please retry." [raw SSE log]), echoed the interrupt (with a non-empty id this time [raw SSE log]), idled both threads with `end_turn`, and sent `session.status_idle` (`end_turn`) 1.1 s after the send. A `user.message` afterwards was accepted and ran a normal turn. A late `user.custom_tool_result` for the closed call was accepted (HTTP 200) and ignored: no echo, no turn.
- **The prompt cache survives a 4-minute wait.** The coordinator's first request after the result, 243 s start-to-start after the request that made the call, read the whole cached prompt: `cache_read_input_tokens` 6,061 of 6,065, plus 378 written for the new tail. Every cache write was a 5-minute write: on the primary thread 7,610 5-minute and 0 1-hour tokens [PROBE P14 docs/probes/2026-10-18.md], and session-wide `ephemeral_5m_input_tokens` 11,449 with `ephemeral_1h_input_tokens` 0 (the last `session.usage`, raw SSE log), so a wait longer than about five minutes start-to-start would write the prompt again [INFERRED from the TTL].
- Cost: 2 US cents for both sessions.

What this means for the choice cards (`docs/superpowers/specs/2026-10-18-plan-creation-ux-design.md` §2, not on main yet; its choice timeout is 240 s) [INFERRED]:

- The research overlaps the pause. Reports that finish during it reach the coordinator only after its first turn on the answer has ended (here two requests, about 2 s). In that turn the coordinator still believes the subagents are working and may act on that (message them, delegate again); the prompt should tell it to end its turn and wait for pending reports after an answer.
- "Interrompi" needs no new path: `user.interrupt` ends the turn with `end_turn` as for a running session (`decide_idle` maps it to `interrupted`). The backend only closes the `choices` row and sends no result.
- **Reconciliation must count `agent.tool_result` as an answer.** `consumer.py` builds the `answered` set from `user.custom_tool_result` only (`app/consumer.py:1561`), so after an interrupt a restarted consumer would see the closed call as pending and answer it again. That is harmless on the platform (the late result above), but PR 2's rule "an `ask_traveller` use without a result is re-armed" would reopen a closed choice. Match `agent.tool_result.tool_use_id` against the custom tool use ids too.
- No second `session.status_idle` tells the consumer that the subagents finished during a pause; the pause needs none (the first `requires_action` idle is already a WAIT).
- The 4-minute timeout keeps the answer inside the 5-minute TTL. The development coordinator is Sonnet 5.5 with a larger prompt (about 17k tokens); the probe used Haiku, and the TTL is assumed to be the platform's for every model.

---

### f. Streaming

#### Session (primary-thread) stream

- **Call:** `client.beta.sessions.events.stream(session_id, event_deltas=[...]?)` → `GET /v1/sessions/{id}/events/stream`. The path is **`/events/stream`**, not `/stream` [SDK resources/beta/sessions/events.py:223-296; offline].
- **Async:** `async with await client.beta.sessions.events.stream(...) as stream: async for ev in stream:` [SDK lib/tools/_beta_session_runner.py:665].
- **`event_deltas`** is opt-in: `["agent.message", "agent.thinking"]`. It adds stream-only `event_start`/`event_delta` previews, which are never persisted [SDK types/beta/beta_managed_agents_delta_type.py] [DOCS reference]. The helper is `anthropic.lib.sessions.accumulate_managed_agents_event` [SDK lib/sessions/_accumulate.py].
- **No replay:** the stream delivers only events emitted after it opens [DOCS events-and-streaming].
- **Heartbeats:** the server sends periodic heartbeats [SKILL shared/managed-agents-events.md]. The *typed* iterator skips SSE `ping` [SDK _streaming.py:295-296]; the raw path recommended below does not (see "The raw path must do the typed iterator's housekeeping").

#### Per-thread stream

- **Call:** `client.beta.sessions.threads.events.stream(thread_id, session_id=sid, event_deltas?)` → `GET /v1/sessions/{sid}/threads/{tid}/stream`. Note it is `/stream`, not `/events/stream` [SDK resources/beta/sessions/threads/events.py:126-209; offline] [SKILL shared/managed-agents-events.md troubleshooting].
- **Content:** the full activity of that agent: `agent.tool_use` and `agent.tool_result`, `agent.mcp_*`, messages, spans [DOCS session-threads] [SDK types/beta/sessions/beta_managed_agents_stream_session_thread_events.py].
- **Previews are thread-scoped:** a child's text previews never appear on the session stream [DOCS session-threads].
- **No replay:** "A thread's stream doesn't replay earlier events … open the thread's stream first, then list the thread's events, and skip each streamed event whose `id` the list returned" [DOCS session-threads].

#### Listing past events (resume)

**Session history:**

```
client.beta.sessions.events.list(sid, limit?, order="asc"|"desc", page?, types?, created_at_gt/gte/lt/lte?)
```

- `GET /v1/sessions/{id}/events`.
- Ordered by `processed_at`, ascending by default.
- Cursor pagination with `next_page`; the SDK auto-paginates when you iterate.
- Default `limit` is 1000 [SKILL shared/managed-agents-events.md].

[SDK resources/beta/sessions/events.py:60-158; offline] [SDK pagination.py:152-173]

**Listed items are SDK models, not the server's JSON.** `item.model_dump(mode="json")` adds every unset optional key as null (`session_thread_id: None` on a `user.interrupt`), reformats timestamps (`...00.123Z` → `...00.123000Z`, while the raw SSE path keeps the server's string), and an unknown `type` is parsed as the union's first variant, `BetaManagedAgentsUserMessageEvent`, with a spurious `content: None` [SDK _models.py:644-649] [SDK _models.py:146-180, 308; offline]. `item.to_dict(mode="json")` drops unset keys but still reformats timestamps. To get the same dicts from the list as from the stream, read the raw body: `resp = await client.beta.sessions.events.with_raw_response.list(sid, ...)`, `body = resp.http_response.json()`, `body["data"]`, `body.get("next_page")` (offline: identical to what the server sent). Same for `threads.events.with_raw_response.list`. Never compare `processed_at` strings across sources; parse them.

**Thread history:**

```
client.beta.sessions.threads.events.list(tid, session_id=sid, limit?, page?)
```

Thread history has **no** `order`, `types` or time filters [SDK types/beta/sessions/threads/event_list_params.py].

**Thread list:**

```
client.beta.sessions.threads.list(sid, statuses?)
```

The list includes the primary thread (`parent_thread_id is None`) [SDK resources/beta/sessions/threads/threads.py:123-185] [DOCS session-threads].

#### Ids, ordering and dedupe

- **Event ids:** every persisted event has `id` (`sevt_...`) and `processed_at` [SDK types/beta/sessions/*] [SKILL shared/managed-agents-events.md]. Ids are opaque and not a sequence. Use your own `seq` for ordering in the UI [INFERRED].
- **Events you send** show `processed_at = null` while queued and appear again once processed. Exceptions: `user.custom_tool_result`, `user.tool_result` and `user.define_outcome` arrive already processed [SKILL shared/managed-agents-client-patterns.md §2].
- **Cross-posted copies** (for example `user.custom_tool_result` routed to a subagent) "can appear on the primary thread and on the subagent's thread with **different `id` values**". Match them on `type` + `custom_tool_use_id`/`tool_use_id` [DOCS session-threads].
- **Interrupt ids:** "Interrupt events may have empty IDs in the current implementation" [SKILL shared/managed-agents-events.md]. Don't store them under a NULL `ma_event_id`: NULLs bypass a UNIQUE constraint, so every resume that lists the history would store the echo again. Derive a deterministic key instead (the backend uses scope + type + `processed_at`, and skips a queued copy without `processed_at`) [INFERRED].
- **Dedupe key:** use `(stream_scope, event_id)`, where `stream_scope` = `"session"` or the thread id, plus semantic dedupe for cross-posts [INFERRED].

#### SDK pitfall: `session.usage` is dropped

The `Stream`/`AsyncStream` iterators only yield SSE events whose `event:` name is on a hard-coded whitelist. `session.usage` is **not** on it [SDK _streaming.py:76-128, 235-287].

**Offline check:** a synthetic SSE body with `event: session.usage` yielded nothing, while `session.status_running`, `session.thread_created`, `agent.custom_tool_use` and `session.status_idle` were yielded.

Workarounds:

- Read the cost via `sessions.retrieve(sid).usage` after each idle.
- Or iterate the raw SSE and validate with `BetaManagedAgentsSessionUsageEvent.model_validate` (checked offline [SDK _streaming.py:56]):

```python
import json
from anthropic import Stream
from anthropic.types.beta import BetaManagedAgentsSessionUsageEvent

with client.beta.sessions.events.with_streaming_response.stream(sid) as resp:
    for sse in Stream.raw_events(resp.http_response):          # raw SSE: nothing is filtered
        if sse.event == "session.usage":
            usage_ev = BetaManagedAgentsSessionUsageEvent.model_validate(json.loads(sse.data))
```

Async version: `AsyncStream.raw_events` [SDK _streaming.py:215].

Unknown future event types are dropped the same way [INFERRED from the same whitelist].

#### The raw path must do the typed iterator's housekeeping

`raw_events` yields every SSE message "before any JSON parsing or event-name filtering" [SDK _streaming.py:214-221]. The typed iterator does three things the raw path must redo [SDK _streaming.py:289-311]:

- it skips `event: ping` (raw yields `('ping', '{}')`);
- it turns `event: error` into an exception (`_make_status_error`, an `APIStatusError` carrying HTTP status 200, e.g. for a mid-stream `overloaded_error`);
- it copies the SSE event name into `type` when the JSON has none (`if is_dict(data) and "type" not in data: data["type"] = sse.event`).

Offline check with a synthetic body: raw yielded `('ping', '{}')`, `(None, '{"id":"sevt_2","type":"agent.message",...}')` for a message without an `event:` line, and `('error', '{"type":"error","error":{"type":"overloaded_error",...}}')`; the typed iterator raised `APIStatusError` (status 200) on the same body. The loop:

```python
async for sse in AsyncStream.raw_events(resp.http_response):
    if sse.event == "ping" or not sse.data.strip():
        continue
    if sse.event == "error":
        raise StreamDisconnectedError(error_type=json.loads(sse.data)["error"]["type"])  # reconnect + backfill
    data = json.loads(sse.data)            # a non-object or invalid payload: reconnect, never drop
    if sse.event:
        data.setdefault("type", sse.event)
    handle(data)                           # dispatch on data["type"], not on sse.event
```

#### Mid-stream drops are raw `httpx2` errors

Once a stream is open the SDK no longer wraps transport errors: a connection reset, a read timeout or a broken chunk surfaces as `httpx2.ReadError`, `httpx2.ReadTimeout` or `httpx2.RemoteProtocolError`, **not** `APIConnectionError` (offline: a body that yields one event and then raises `httpx2.ReadError` gave `isinstance(e, anthropic.APIConnectionError) == False`, `isinstance(e, httpx2.HTTPError) == True`, on both the raw and the typed path). Catch `httpx2.HTTPError` together with `anthropic.APIError` while iterating, as the SDK's own runner does: `TRANSIENT_ERRORS = (httpx2.HTTPError, APIError)` [SDK lib/_retry.py:24], used at [SDK lib/tools/_beta_session_runner.py:688], minus the fatal 4xx of `is_fatal_status_error` [SDK lib/_retry.py:42-48].

#### Minimal Python: consumer skeleton

```python
async def follow(client, sid, seen: set[str], handle):
    async with await client.beta.sessions.events.stream(sid) as stream:          # 1. open first
        async for past in client.beta.sessions.events.list(sid, limit=1000):     # 2. backfill
            if past.id and past.id not in seen:
                seen.add(past.id); await handle(past)
        async for ev in stream:                                                   # 3. tail
            if ev.type in ("event_start", "event_delta"):
                continue
            if ev.id and ev.id in seen:
                continue
            seen.add(ev.id); await handle(ev)
            if ev.type == "session.thread_created":
                spawn(follow_thread(client, sid, ev.session_thread_id))          # same pattern on the thread stream
            if ev.type == "session.status_terminated":
                return
```

This follows the documented reconnect pattern and the SDK runner [DOCS events-and-streaming] [SDK lib/tools/_beta_session_runner.py:657-700]. The `spawn` and `follow_thread` structure is [INFERRED]. (The skeleton uses the typed iterator for brevity; the backend uses the raw path above.)

**Mid-stream drops are not retried by the SDK.** Reconnect with capped backoff, as the SDK's runner does: 0.5 s, 1 s, 2 s, 4 s, 8 s, then a 10 s cap, reset to 0.5 s after any received event [SDK lib/tools/_beta_session_runner.py:108-109, 668, 700].

#### Reconcile after a reconnect (custom tool calls)

The SDK ships a reference implementation of resume plus custom-tool reconciliation: `client.beta.sessions.events.tool_runner(session_id, tools=..., max_idle=...)` returns a `SessionToolRunner` that answers `agent.custom_tool_use` with `user.custom_tool_result` (and `agent.tool_use` with `user.tool_result`) [SDK resources/beta/sessions/events.py:559-654]. Its rules, which the backend's consumer copies for `submit_plan`:

- **Open the stream before reconciling**, so an event emitted between the list and the attach is delivered live [SDK lib/tools/_beta_session_runner.py:657-666].
- **Read the whole history first, then decide (two passes):** pending = ids of `agent.custom_tool_use` minus the `custom_tool_use_id` of every `user.custom_tool_result` in history (and `tool_use_id` for built-in tools). A call whose result appears later in the same history is never re-dispatched [SDK lib/tools/_beta_session_runner.py:574-597].
- **If a list call fails partway, act on nothing and roll back:** the ids added to "seen" during the failed pass are removed, so the live stream can still process them and the next reconnect reconciles again [SDK lib/tools/_beta_session_runner.py:598-627].

The runner itself is not used here: it yields only tool calls, and the backend needs every event for the UI [INFERRED].

#### Webhooks (optional, not in the MVP)

The SDK also verifies Managed Agents webhooks: `client.beta.webhooks.unwrap(payload, headers=..., key=...)` checks the `webhook-id` / `webhook-timestamp` / `webhook-signature` headers with the webhook signing key (`webhook_key`, env `ANTHROPIC_WEBHOOK_SIGNING_KEY`) and needs `anthropic[webhooks]` [SDK resources/beta/webhooks.py:29-60]. Session event types include `session.requires_action`, `session.budget_reached`, `session.status_idled`, `session.status_terminated`, `session.thread_idled`, `session.thread_terminated`, `session.archived`, `session.deleted` [SDK types/beta/beta_webhook_session_*_event_data.py; e.g. beta_webhook_session_budget_reached_event_data.py:8-16 carries the session `id`]. They would tell the backend about `budget_reached` or `requires_action` while no consumer has a stream open (after a restart or a long disconnect). Not used: it needs a public HTTPS endpoint and its own auth, and the resume on process start already covers those cases [INFERRED].

---

### g. Event catalog

All events persisted in the stream and in history are in [SDK types/beta/sessions/beta_managed_agents_session_event.py]. The stream adds `event_start` and `event_delta` [SDK types/beta/sessions/beta_managed_agents_stream_session_events.py]. Common fields on every event: `id`, `type`, `processed_at`.

**Agent events**

| Type | Extra fields | Notes |
|---|---|---|
| `agent.message` | `content: [text \| redacted]` | |
| `agent.thinking` | none | A progress signal only, no content. |
| `agent.tool_use` | `name`, `input`, `evaluated_permission` (`allow`/`ask`/`deny`), `evaluation`, `session_thread_id?` | `session_thread_id` is set only on cross-posted copies. |
| `agent.tool_result` | `tool_use_id`, `content?`, `is_error?` | |
| `agent.mcp_tool_use` | `mcp_server_name`, `name`, `input`, `evaluated_permission`, `evaluation`, `session_thread_id?` | |
| `agent.mcp_tool_result` | `mcp_tool_use_id`, `content?`, `is_error?` | |
| `agent.custom_tool_use` | `name`, `input`, `session_thread_id?` | The session goes idle (`requires_action`). |
| `agent.thread_message_sent` | `to_session_thread_id`, `to_agent_name?`, `content` | On the primary stream: the coordinator → a subagent (task or follow-up). |
| `agent.thread_message_received` | `from_session_thread_id`, `from_agent_name?`, `content` | On the primary stream: a subagent → the coordinator (report or question). Direction is relative to the stream that carries the event. |
| `agent.thread_context_compacted` | none | |

**Session status events**

| Type | Extra fields | Notes |
|---|---|---|
| `session.status_running` | none | |
| `session.status_idle` | `stop_reason`, `stop_details?` | `stop_reason.type` values below. |
| `session.status_rescheduled` | none | Transient error; the platform retries. |
| `session.status_terminated` | none | Unrecoverable error **or archive**. |
| `session.deleted` | none | Ends the stream. |
| `session.updated` | `agent?`, `budget?` (null = removed), `metadata?`, `title?` | |
| `session.usage` | `usage: {list_cost, tokens, server_tool_use, active_seconds, cache_creation}`, `budget?` | Emitted before every idle. Dropped by the 1.13.0 iterator (§2f). |
| `session.error` | `error: {type, message, retry_status: {type: retrying \| exhausted \| terminal}, ...}` | Error types below. |

`stop_reason.type` values on `session.status_idle`:

- `end_turn`: also the value after an interrupt.
- `requires_action` (carries `event_ids: [..]`).
- `retries_exhausted`.
- `budget_reached`.
- `refusal`: `stop_details` carries `category` (`cyber` \| `bio` \| `frontier_llm` \| `reasoning_extraction` \| `general_harms` \| null) and `explanation`.

`session.error` error types:

- `unknown_error`
- `model_overloaded_error`
- `model_rate_limited_error`
- `model_request_failed_error`
- `mcp_connection_failed_error` and `mcp_authentication_failed_error` (both with `mcp_server_name`)
- `billing_error`
- `credential_host_unreachable_error`
- `repository_authentication_error`, `repository_forbidden_error`, `repository_not_found_error`, `repository_checkout_error`, `repository_clone_error`

**Thread events**

| Type | Extra fields | Notes |
|---|---|---|
| `session.thread_created` | `session_thread_id` (`sthr_...`), `agent_name`, `workflow_run_id?` | Written to the parent's stream. |
| `session.thread_status_running` / `_rescheduled` / `_terminated` | `session_thread_id`, `agent_name` | On the thread's own stream, and cross-posted to the primary stream for child threads. |
| `session.thread_status_idle` | `session_thread_id`, `agent_name`, `stop_reason`, `stop_details?` | Same placement as above. |

**Span events**

| Type | Extra fields |
|---|---|
| `span.model_request_start` | none |
| `span.model_request_end` | `model_request_start_id`, `is_error?`, `model_usage: {input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, speed?}` |
| `span.outcome_evaluation_start` | `outcome_id`, `iteration` |
| `span.outcome_evaluation_ongoing` | `outcome_id`, `iteration` |
| `span.outcome_evaluation_end` | `outcome_id`, `iteration`, `result` (`satisfied` \| `needs_revision` \| `max_iterations_reached` \| `failed` \| `interrupted`), `explanation`, `usage` |

**User and system echoes**

- `user.message`, `user.interrupt`, `user.custom_tool_result` (with `session_thread_id` set by the server when routed to a subagent), `user.tool_confirmation`, `user.tool_result`, `user.define_outcome` (with `outcome_id`), `system.message`.

**Workflow events**

- `workflow_run.created`, `.status_running`, `.status_idle`, `.status_ended`, `.error`, `.phase_started`, `.phase_ended`.
- Irrelevant here because the spec sets `workflows: {type: "disabled"}`.

**Stream-only events**

- `event_start` carries `event: {type, id}`.
- `event_delta` carries `event_id` and `delta: {type: "content_delta", index, content: text}`.

**Sources** for the tables above, all under `types/beta/sessions/` unless stated: `beta_managed_agents_agent_*_event.py`, `beta_managed_agents_session_*_event.py`, `beta_managed_agents_session_end_turn.py`, `beta_managed_agents_session_requires_action.py`, `beta_managed_agents_session_retries_exhausted.py`, `beta_managed_agents_session_budget_reached.py`, `beta_managed_agents_session_refusal*.py`, `beta_managed_agents_span_*.py`, `beta_managed_agents_retry_status_*.py`, `beta_managed_agents_session_error_event.py`, plus `types/beta/beta_managed_agents_session_usage_event.py`, `beta_managed_agents_session_updated_event.py`, `beta_managed_agents_start_event.py` and `beta_managed_agents_delta_event.py` [SDK]. Event type list and descriptions: [DOCS reference].

#### `send_to_agent` / `list_agents`

| Who | What is known | Source |
|---|---|---|
| Coordinator (primary thread) | Receives the delegation tools `list_agents` and `send_to_agent`. | [SKILL shared/managed-agents-multiagent.md] |
| Advisor | Invisible to `list_agents` and unreachable through `send_to_agent`. | [SKILL same file] |
| Subagents | Send reports, and possibly questions, to the coordinator. Arrives as `agent.thread_message_received` on the primary stream. | [DOCS session-threads] |
| Subagent → sibling | No documentation found. | Probe P6 |
| Any agent | Neither tool name appears in the SDK. They are server-side tools, so they would show up as `agent.tool_use` events with those names. | [INFERRED] |

---

### h. The `ant` CLI

#### What it is

`ant` is the official CLI for the Claude Platform (a Go binary). It wraps every API resource; `beta:` subcommands set the beta header automatically [DOCS https://github.com/anthropics/anthropic-cli/blob/main/README.md] [SKILL shared/anthropic-cli.md]. The latest release is v1.40.0, published 2026-10-09 [DOCS https://api.github.com/repos/anthropics/anthropic-cli/releases/latest]. `ant apply` needs v1.30.0 or later [DOCS cli/apply].

#### How to install

Sources: [DOCS https://platform.claude.com/docs/en/cli-sdks-libraries/cli/quickstart] [DOCS anthropic-cli README].

| Method | Command |
|---|---|
| Homebrew | `brew install anthropics/tap/ant`, then `xattr -d com.apple.quarantine "$(brew --prefix)/bin/ant"` on macOS [SKILL shared/anthropic-cli.md] |
| GitHub release | `ant_1.40.0_macos_arm64.zip` (10.3 MB), also `linux_*.tar.gz`, `.deb`, `.rpm` |
| From source | `go install github.com/anthropics/anthropic-cli/cmd/ant@latest` (Go 1.22+; the docs say 1.25+) |
| CI | This repository's own `.github/actions/setup-ant` (downloads the pinned `ant_<version>_linux_amd64.tar.gz` release and checks its sha256). `uses: anthropics/setup-ant@v1`, the documented action, answered 404 on 2026-10-12 |

**There is no npm package.** `@anthropic-ai/cli`, `@anthropic-ai/ant` and `anthropic-cli` all return 404 (checked with `npm view`).

**Don't use PyPI `anthropic-cli` 0.2.3.** It is an unrelated third-party package by David Mohl (github.com/dvcrn/anthropic-cli) and must **not** be installed (checked against the PyPI JSON API).

#### Status on this machine

`ant` is **not installed**. Homebrew is present (`/opt/homebrew/bin/brew`), the tap isn't added, and `go` is absent. I did **not** install it, because downloading and running a binary needs your explicit approval.

All `ant apply` behaviour below comes from the official docs and from reading the official Go source on GitHub. The CLI binary itself is unverified. Probe step P12 verifies it with `--dry-run` once it is installed.

#### `ant apply` input formats

Sources: [DOCS cli/apply] [DOCS anthropic-cli README] [DOCS https://github.com/anthropics/anthropic-cli/blob/main/internal/declarative/claude/kinds.go].

- **Agent: `agents/<name>.md`.** YAML frontmatter = the `POST /v1/agents` body; the Markdown body becomes `system`. The file can also be `.yaml` or `.json`.
- **Environment: `environments/<name>.yaml`.** Holds the `POST /v1/environments` body. In `.md` form, the body text becomes `description`.
- **Skill: a directory with `SKILL.md`** at its root, conventionally `skills/<name>/`. It is uploaded as one bundle; a changed file becomes a new skill version.
- **Also supported:** memory stores (`memory_stores/`), deployments (`deployments/`), vaults (`vaults/`).

**How a file's kind is inferred** (first match wins):

1. A top-level `type:` field. The CLI strips it before sending [DOCS https://github.com/anthropics/anthropic-cli/blob/main/internal/declarative/core/source.go:117].
2. The directory the file sits **directly** in (`agents/`, `environments/`, …).
3. A filename that starts with the kind, for example `environment_staging.md`.

Files that match none of these are skipped during a directory walk. When named on the command line, a Markdown file defaults to an agent. So the spec's root-level `environment.yaml` matches rule 3 [INFERRED]. `environments/<name>.yaml` is the documented convention.

#### References between files (replaces `$AGENT_X` / `$SKILL_X`)

- **Write a relative path** from the declaring file wherever an ID is expected. `ant apply` resolves it to `{type: "custom", skill_id, version}` for skills and to `{type: "agent", id, version}` for agents [DOCS kinds.go] [DOCS https://github.com/anthropics/anthropic-cli/blob/main/internal/declarative/core/refs.go].
- **Pinning:** a path reference **pins** the version just applied, and the coordinator is re-pinned in the same run when a subagent changes. Write `{path: ./flights.md, version: latest}` to leave a reference unpinned; an exact version needs a literal ID instead of a path [DOCS refs.go].
- **Literal IDs:** a tagged string such as `agent_...` or `skill_...` is sent as an ID.
- **Pass-through:** any object without `path` (for example `{type: anthropic, skill_id: xlsx}`) is sent unchanged [DOCS refs.go].

**Including tool definitions from data files:** `tools` and `mcp_servers` accept string entries `- ./tools/*.json`, `.yml` or `.yaml`. Each file holds one object or a list of objects, and they are spliced into the list. The data file must not sit directly in a kind directory such as `agents/`; use a subdirectory like `agents/tools/` [DOCS https://github.com/anthropics/anthropic-cli/blob/main/internal/declarative/core/include.go]. This is the supported way to keep the generated `submit_plan` schema in a file:

```markdown
---
# agents/coordinator.md
name: coordinator
model: claude-opus-5-5
tools:
  - type: agent_toolset_20260401
    default_config: {enabled: false}
    configs:
      - {name: read, enabled: true}
      - {name: write, enabled: true}
      - {name: glob, enabled: true}
  - ./tools/submit_plan.json        # {"type":"custom","name":"submit_plan","description":...,"input_schema":{...}}
skills:
  - ../skills/trip-tracker-schema
  - ../skills/travel-research-rules
multiagent:
  type: multiagent_20261001
  subagents:
    type: enabled
    inline_agents: {type: disabled}
    predefined_agents:
      - ./flights.md
      - ./lodging.md
      - ./activities.md
      - ./transport.md
  workflows: {type: disabled}
  advisor: {type: disabled}
---
You are the trip-planning coordinator. ...
```

`multiagent.subagents.predefined_agents` is a declared reference slot [DOCS kinds.go]. This exact file is unverified until P12 [INFERRED].

#### Lockfile: `claude-lock.json`

It is written where you run the command, or at the `--lock-file` path, and committed [DOCS cli/apply]. This project keeps one per profile at `backend/claude-lock.<profile>.json`, applied from the repo root (next sections), because Railway deploys the backend from the root directory `backend/` and ships only that directory, and the backend reads the lockfile at runtime. Shape:

```json
{
  "version": 1,
  "origin": {"base_url": "https://api.anthropic.com", "organization_id": "...", "workspace_id": "wrkspc_..."},
  "resources": {
    "../profiles/development/agents/coordinator.md": {"kind": "agent", "id": "agent_...", "version": "3", "hash": "...", "remote_hash": "..."},
    "../profiles/development/environments/cloud.yaml": {"kind": "environment", "id": "env_...", "hash": "...", "remote_hash": "..."},
    "../skills/booking-links": {"kind": "skill", "id": "skill_...", "version": "<latest_version_id>", "hash": "...", "remote_hash": "..."}
  }
}
```

- **Keys are paths relative to the lockfile's directory**, not to the directory `ant` runs in. In ant v1.40.0, `pkg/cmd/apply.go` builds the loader with `lock.Root()`, `core/lock.go` defines `Root()` as `filepath.Dir(lf.Path)`, and `core/loader.go` `keyFor` writes each path relative to it with a `./` or `../` prefix (read on GitHub, 2026-10-12). So `backend/claude-lock.<profile>.json` holds `../profiles/<profile>/...` and `../skills/<name>`; the example above is that lockfile.
- `version` is always a string. For skills `ant` uses the **Beta** skills API (`sdk.Beta.Skills`) and records the skill's `latest_version_id`, or a legacy `latest_version`, which can be an epoch-like digit string; `scripts/bootstrap.py` uses the GA API and records a `skver_...` id [DOCS https://github.com/anthropics/anthropic-cli/blob/main/internal/declarative/core/version.go] [DOCS kinds.go]. The entry shape is `{kind, id, version, hash}` plus `remote_hash`, as ant's `record()` writes it.
- **The backend reads IDs** with `resources["../profiles/<profile>/agents/coordinator.md"].id` and `.version` (`backend/app/lockfile.py`). It accepts any plain-token skill version (it only records it) and still resolves the first bootstrap.py's repository-root keys (`./profiles/...`, `./skills/...`) with the warning `lockfile_legacy_keys`.
- **Drift:** if a resource was changed outside the files, `ant apply` refuses to run until you pass `--force` [DOCS cli/apply].
- **Concurrency:** run one apply at a time; nothing locks the lockfile [DOCS cli/apply].

**Flags:**

| Flag | Effect |
|---|---|
| `--dry-run` | Prints the plan and exits 0, even when the plan is blocked. |
| `--yes` | Required when there is no terminal. |
| `--force` | Applies even where a resource was changed outside the files. |
| `--prune` | Removes resources whose files were deleted. |
| `--upgrade` | Re-resolves skills referenced by GitHub URL. |
| `--lock-file <path>` | Uses a specific lockfile. Keep one per organization or workspace. |
| `-v` | Shows unchanged resources and full field values. |

[DOCS cli/apply]

**CI:** authenticate through Workload Identity Federation (`ANTHROPIC_IDENTITY_TOKEN_FILE`, `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID`, optional `ANTHROPIC_WORKSPACE_ID`) [DOCS anthropic-cli README CI example]. Verified in anthropic 1.13.0 (`anthropic/lib/credentials/`) and anthropic-cli (`pkg/cmd/extras.go`): both read those variables and re-read the token file on every exchange; the exchange is a `jwt-bearer` grant on `/v1/oauth/token` with beta header `oidc-federation-2026-04-01`; a static `ANTHROPIC_API_KEY` (or `ANTHROPIC_AUTH_TOKEN`) wins over federation, so it must not be set in those jobs; passing `api_key=` to the SDK client disables federation. The rule needs `oauth_scope: workspace:developer` for `ant apply` and an exact `subject_prefix` plus an explicit `audience`; GitHub's token lives minutes, so a long job must rewrite the file (and the issuer's single-use `check_jti` is best off). The README's example mints with `audience=anthropic`; this repository uses `https://api.anthropic.com` and sets it in the rule. Setup and rationale: docs/deploy.md, "Anthropic Workload Identity Federation". The federation admin endpoints refuse Admin API keys (they need an `org:admin` OAuth token from `ant auth login --scope org:admin`).

#### Two profiles (development / production)

A design proposal [INFERRED], to be validated in P12:

- Separate files per profile, because the models differ and `ant` has no templating. Session `agent_with_overrides` can't change roster agents' models [SKILL shared/managed-agents-core.md]. As built, the prompts are written once in `agents/*.md` (templates, models and numbers from `agents/profiles.yaml`) and `scripts/render_profiles.py` generates both profiles.
- Layout: `profiles/development/agents/*.md`, `profiles/development/environments/cloud.yaml`, the same under `profiles/production/`, and shared `skills/<name>/`, referenced as `../../../skills/<name>`.
- One lockfile per profile, `backend/claude-lock.<profile>.json`, applied from the repo root with `ant apply --lock-file backend/claude-lock.<profile>.json profiles/<profile>`. This works whether the two keys share a workspace or not. It sits in `backend/` because Railway ships only that directory; the backend picks it with `AGENT_PROFILE` (`LOCKFILE_PATH` defaults to it). Keys come out relative to `backend/`: `../profiles/<profile>/agents/<name>.md` and `../skills/<name>` (see "Lockfile" above).

#### If `ant` can't be used: what `scripts/bootstrap.py` must do with the SDK

Inputs are the same files. Steps in order [INFERRED, built on the SDK calls verified above]:

1. **Parse inputs.** Read `agents/*.md` (YAML frontmatter + body → `system`), the environment YAML and `skills/*/`.
2. **Resolve references.** Turn relative paths in `skills`, `multiagent.subagents.predefined_agents` and `tools` include entries into ids, the same way `ant` does.
3. **Load state.** Open the profile's lockfile, keeping the `ant` format above so `ant` can take over later.
4. **Upload skills.** For each `skills/<name>/`, build the file list with `ant`'s exclusions (§2c "Rules and limits": skip dotfiles such as `.DS_Store`, `__pycache__`, `.venv`, `node_modules`, `dist`, `build` and symlinks), because `files_from_dir` is unfiltered [SDK lib/_files.py:11-25]; hash that list (path + content).
   - New: `client.skills.create(files=<filtered list>)` → record `id` and `latest_version_id`.
   - Changed: `client.skills.versions.create(id, files=<filtered list>)` → record the new version `id`.
5. **Sync the environment.** `client.beta.environments.create(...)` the first time; afterwards `update(env_id, config=...)` when the hash changes. Names must be unique per workspace.
6. **Sync the subagents** (flights, lodging, activities, transport):
   - Build each body with skill refs `{"type": "custom", "skill_id": id, "version": version_id}`.
   - Include the MCP toolsets with `always_allow`.
   - `client.beta.agents.create(**body)`, or, when the hash changed, `client.beta.agents.update(id, version=<lock version>, **body)`. This is optimistic concurrency: a version conflict is a 409, which the SDK **retries like a lock timeout** unless the call is sent with `client.with_options(max_retries=0)` [SDK _base_client.py:876-884]. Send it that way and handle the 409 by re-reading.
   - Record `id` and the returned `version` (int).
7. **Sync the coordinator** last:
   - `predefined_agents = [{"type": "agent", "id": id, "version": v} ...]` using the versions just recorded.
   - Inline the `submit_plan` tool with `input_schema` = the dereferenced `Plan.model_json_schema()`, root `{"type": "object", ...}`.
   - Always send the **complete** `multiagent` object (`type`, `subagents` with `inline_agents` and `predefined_agents`, `workflows: {type: disabled}`, `advisor`), never a partial one or a `null` sub-key: the SDK documents both "merged level by level" and "full replacement" for it (§2a "Versions", §3), and only a complete object means the same under both.
   - Create or update it the same way.
8. **Write the lockfile** with `id`, `version` and `hash`. Print a plan, and require `--yes` to apply. Never run it implicitly from the backend.

The backend only **reads** the lockfile and calls `sessions.create(agent={"type": "agent", "id", "version"})`.

---

### i. Model IDs

`BetaManagedAgentsModel` lists these literals [SDK types/beta/beta_managed_agents_model.py] [SDK types/beta/beta_managed_agents_model_param.py]:

> `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-fable-5-1`, `claude-sonnet-5`, `claude-fable-5`, `claude-opus-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`, `claude-haiku-4-5-20251001`, `claude-opus-4-5`, `claude-opus-4-5-20251101`, `claude-sonnet-4-5`, `claude-sonnet-4-5-20250929`

The top-level `Model` type has the same literals plus Mythos [SDK types/model.py].

| Model | Exists? | Price per MTok (input / output) | Cache read |
|---|---|---|---|
| `claude-opus-5-5` | yes | $4 / $20 | $0.20 |
| `claude-sonnet-5-5` | yes | $2 / $10 | $0.10 |
| `claude-haiku-5-5` | yes | $0.10 / $0.50 for prompts ≤100k tokens; $0.50 / $2.50 above | |
| `claude-haiku-4-5` | yes | $1 / $5 | |

Prices: [DOCS pricing].

- **`claude-haiku-5-5` is confirmed** for the development profile: it is in the SDK and in the official multiagent examples [DOCS multiagent-orchestration].
- **Note:** the cached skill's model table omits Haiku 5.5 and calls `claude-haiku-4-5` the current Haiku [SKILL SKILL.md]. That table is stale.
- **Observed Haiku 5.5 billing:** in the first dev eval session every Haiku request was priced at the over-100k tier ($0.50 in, $0.625 cache write, $0.05 cache read, $2.50 out) although the prompts were far below 100k tokens: three threads fit within 1c (§5 "What a session costs"). Plan with those rates, not the ≤100k ones.
- **Spec cost estimate:** the development-profile figures (l.874, about $0.08 for four Haiku 5.5 subagents) match the ≤100k price tier [INFERRED arithmetic].
- **Budgets need a list price:** a budgeted session is rejected (400) if any roster model lacks a public list price. All four models above have one [DOCS budgets].

---

### j. Errors and retries

#### HTTP errors

The SDK raises one class per status [SDK _client.py:551-587] [SDK _exceptions.py]:

| Status | Exception |
|---|---|
| 400 | `BadRequestError` |
| 401 | `AuthenticationError` |
| 403 | `PermissionDeniedError` |
| 404 | `NotFoundError` |
| 409 | `ConflictError` |
| 413 | `RequestTooLargeError` |
| 422 | `UnprocessableEntityError` |
| 429 | `RateLimitError` |
| 529 | `OverloadedError` |
| ≥500 | `InternalServerError` |
| any other (408 included) | plain `APIStatusError` |
| transport, before the response | `APIConnectionError` / `APITimeoutError` |
| transport, mid-stream | raw `httpx2.HTTPError` (`ReadError`, `ReadTimeout`, `RemoteProtocolError`), **not** wrapped (§2f) |

A 409 carries `error.type: invalid_request_error` [SKILL shared/managed-agents-api-reference.md]. There is no 408 class [SDK _client.py:979-1015 (async)], so classify errors **by `status_code`**, not by class: 408, 409, 429 and ≥500 are what the SDK itself treats as transient (`_RETRYABLE_4XX = {408, 409, 429}`, `is_fatal_status_error` [SDK lib/_retry.py:29-48]).

#### Built-in retry

[SDK _base_client.py:837-921] [SDK _constants.py]

- **Retried by default:** 408, 409, 429, any status ≥500 (including 529 overload) and connection errors. The server header `x-should-retry: true|false` overrides this. Every 409 is retried, including a conflict that can't resolve itself (archiving a `running` session, an `agents.update(version=...)` conflict): send those with `max_retries=0` (offline: `max_retries=5` + an always-409 transport made 6 attempts before `ConflictError`).
- **Default** `max_retries` is **2** (confirmed offline: `DEFAULT_MAX_RETRIES: 2`). It counts retries **after** the first attempt: `for retries_taken in range(max_retries + 1)` [SDK _base_client.py:1159], so a failing call makes `max_retries + 1` HTTP attempts.
- **Backoff:** `min(0.5 * 2^n, 8.0)` seconds × a jitter factor of 0.75-1.0 [SDK _constants.py:14-15] [SDK _base_client.py:852-861].
- **Server-requested delay wins, almost uncapped:** `retry-after-ms` is read first, then `retry-after` (seconds or an HTTP date) [SDK _base_client.py:812-834], and any positive value is used up to `4_294_967` s, about 49.7 days, not the 60 s cap of older Stainless SDKs [SDK _base_client.py:846-850]. The per-request `timeout` does not bound these sleeps, so one 429/529 with a large `retry-after` can block a call for minutes or hours. Bound every latency-sensitive call from outside (`asyncio.timeout(...)`; the backend uses 120 s) or lower its `max_retries`.
- **Default timeout:** 600 s, connect 5 s.

**How to configure** [SDK _client.py:157-168, 468-526]:

- Per client: `anthropic.Anthropic(max_retries=4, timeout=...)` (5 attempts in total).
- Per call: `client.with_options(max_retries=0).beta.sessions.archive(...)`.

#### Rate limits

| Source | Create endpoints | Read endpoints | Environments |
|---|---|---|---|
| Docs | 300 RPM per organization | 1,200 RPM | not stated |
| Skill | 300 RPM | 600 RPM | 60 RPM, 5 concurrent |

[DOCS reference §Rate limits] [SKILL shared/managed-agents-api-reference.md]. Docs win.

#### What is not covered by the SDK retries

- **Mid-stream SSE drops:** the SDK doesn't retry them, and they arrive as raw `httpx2.HTTPError` subclasses, not `APIConnectionError` (§2f). An `event: error` message mid-stream is the same situation on the raw path. Reconnect with stream-then-list (§2f) [SDK _streaming.py] [SDK lib/tools/_beta_session_runner.py:657-700].
- **Non-idempotent sends:** a retried `user.message` may be enqueued twice [INFERRED]. A retried `user.custom_tool_result` is harmless ("A second result for the same call is accepted and has no effect" [DOCS events-and-streaming]).
- **In-session errors** arrive as `session.error` events, not HTTP errors. Read `retry_status`:
  - `retrying`: the server retries, so wait.
  - `exhausted`: the turn is dead; queued inputs are flushed, the session goes idle, and you may send a new prompt.
  - `terminal`: the session will terminate.

  [SDK types/beta/sessions/beta_managed_agents_retry_status_*.py]
- **`retries_exhausted` stop reason:** the turn ended after repeated errors [SDK types/beta/sessions/beta_managed_agents_session_retries_exhausted.py].
- **`billing_error`:** retrying with the same credentials will not help [SDK types/beta/sessions/beta_managed_agents_billing_error.py].

**Mapping to the spec** (l.1226-1227): set `max_retries=4` on the backend client, so a call makes at most 5 attempts, and bound each call with a deadline [INFERRED]. Treat `session.status_rescheduled` and `retry_status: retrying` as "wait". Mark the plan `failed` on `retry_status: terminal`, on `stop_reason: retries_exhausted`, or when HTTP calls still fail after those 5 attempts.

---

## 3. Contradictions with the spec

1. **`input_schema: { $ref: schema/plan.json }` (l.181) is not supported.**
   - The API needs an inline object with `type: "object"` [SDK types/beta/beta_managed_agents_custom_tool_input_schema_param.py].
   - `ant apply` has no `$ref` [DOCS cli/apply].
   - Fix: generate a whole tool file and list it in `tools` as `- ./tools/submit_plan.json` [DOCS anthropic-cli README / include.go], or inline it in `scripts/bootstrap.py`.
   - Also probe whether `$defs` and internal `$ref` *inside* the schema are accepted (P2).

2. **`$SKILL_...` / `$AGENT_...` placeholders (l.184-193) don't exist in `ant apply`.**
   - Use relative paths (`../skills/trip-tracker-schema`, `./flights.md`). The objects as written would be sent literally [DOCS refs.go].

3. **`limited` networking with `allowed_hosts` for Photon and Open-Meteo only (l.254-257).**
   - Per the current docs, this **also restricts `web_search` and `web_fetch`** to those two hosts [DOCS environments] [DOCS tools-web-restrictions], which would cripple flight, lodging and activity research.
   - The spec's own risk table (l.1333-1337) assumes this has low probability.
   - Options [INFERRED]:
     - (a) Use `unrestricted`, the spec's own fallback, and restrict the web tools per agent with `blocked_domains`.
     - (b) Enumerate every needed travel and tourism host in `allowed_hosts`. They also open to the sandbox; `*.domain` wildcards are allowed.
   - Decide after P5.

4. **"development usa sempre l'ultima" (l.1087-1088).**
   - `predefined_agents` are always pinned at coordinator save time [DOCS multiagent-orchestration §Pinning].
   - Development therefore also needs a coordinator re-apply after every subagent change. `ant apply` does it automatically with path references [DOCS anthropic-cli README].

5. **`budget.max_list_cost` a `"400"` (l.883) is incomplete shorthand.**
   - The real shape is `{"type": "limit", "max_list_cost": {"amount": "400", "currency": "USD"}}` [SDK types/beta/beta_managed_agents_budget_limit_param.py].
   - `SESSION_BUDGET_CENTS` must be sent as an integer string [DOCS budgets].

6. **One lockfile holding both profiles with separate keys (l.259-261, l.1161) conflicts with lockfile workspace binding** when the keys belong to different workspaces [DOCS cli/apply §Flags `--lock-file`]. See the layout in §2h.

7. **Cost tracking through `session.usage` (l.880, l.637).**
   - The event exists and is emitted before every idle [DOCS budgets].
   - `anthropic==1.13.0` drops it from `events.stream()` iteration [SDK _streaming.py; offline]. Use raw SSE or `sessions.retrieve().usage`.

8. **`events.ma_event_id` unique for dedupe (l.670-672).**
   - Cross-posted copies of the same logical event can have **different** ids on the primary and thread streams [DOCS session-threads].
   - Interrupt events may have an **empty** id [SKILL shared/managed-agents-events.md].
   - Scope the key per stream, and give empty-id events a deterministic synthetic key rather than NULL (§2f "Ids, ordering and dedupe") [INFERRED].

9. **Consumer step 2 (l.618)**, "per ogni `session.thread_created` apre lo stream del thread":
   - Thread streams don't replay. The consumer must open the thread stream **and then list that thread's events**, skipping ids already seen [DOCS session-threads].
   - On restart (step 6), enumerate threads with `sessions.threads.list(sid)` and backfill each one [INFERRED].

10. **Retries "massimo 5 tentativi" (l.1226).** The SDK default is 2 retries, and `max_retries` counts retries after the first attempt; set `max_retries=4` explicitly for 5 attempts in total [SDK _constants.py] [SDK _base_client.py:1159].

11. **Archiving after `end_turn` (l.629).** Archive and delete fail while the session is `running`, and the idle event precedes the status write. Poll before archiving [DOCS session-operations] [SKILL shared/managed-agents-client-patterns.md §6].

### Source conflicts (not about the spec)

| Topic | SDK / docs | Skill | Resolution |
|---|---|---|---|
| Echo `session_thread_id` in `user.custom_tool_result` | No such parameter; the event docstring says "clients do not send it back" [SDK types/beta/sessions/beta_managed_agents_user_custom_tool_result_event_params.py] [SDK types/beta/sessions/beta_managed_agents_agent_custom_tool_use_event.py]. Docs say the server routes it automatically [DOCS session-threads]. | Says to echo it [SKILL shared/managed-agents-multiagent.md] | **Don't send it.** |
| Web tools under `limited` networking | Restricted by `allowed_hosts` [DOCS] | Not restricted [SKILL] | See item 3 above. |
| Session `metadata` limit | 16 pairs [SDK] | 8 keys [SKILL shared/managed-agents-core.md] | SDK wins. |
| Max tools per agent | 256 [SDK] | 128 [SKILL] | SDK wins. |
| Rate limits | See §2j [DOCS] | See §2j [SKILL] | Docs win. |
| Current Haiku | `claude-haiku-5-5` exists [SDK] [DOCS] | Calls `claude-haiku-4-5` current [SKILL] | SDK and docs win. |
| `agents.update(multiagent=...)` semantics | The params type: a `multiagent_20261001` object is "merged into the stored one, level by level"; `null` sub-keys take their defaults [SDK types/beta/beta_managed_agents_multiagent20261001_params.py:16]. The update method and its params: "Full replacement. Omit to preserve; send null to clear" [SDK types/beta/agent_update_params.py:49-53] [SDK resources/beta/agents/agents.py:282]. The SDK disagrees with itself. | not covered | **Always send the complete object** (§2a "Versions", §2h step 7), so both readings agree; P12 retrieves after an update and diffs. |

---

## 4. Live probe checklist for `scripts/probe_session.py`

Use a **development key** only.

**Cost guard** for every step that creates a session:

- All agents use `claude-haiku-5-5`, except where a step needs the real roster.
- `budget={"type": "limit", "max_list_cost": {"amount": "25", "currency": "USD"}}` ($0.25) per session.
- Archive and delete each session at the end.

Expected total under $1 [INFERRED]. Log every raw SSE line to a file. Never run this probe from CI or from the backend.

| # | Probe | How | Decides |
|---|---|---|---|
| P1 | Environment shape | `environments.create` with `limited`, `allowed_hosts` [photon, open-meteo], `allow_mcp_servers: true`. Retrieve it and diff the echo. Repeat with an identical name and expect 409. | §2b fields; unique names |
| P2 | `submit_plan` schema | `agents.create` with the raw `Plan.model_json_schema()`, which contains `$defs`/`$ref`, `anyOf: [.., {type: null}]`, `format: uri/date-time`, `pattern`, `exclusiveMinimum`, `maxLength`. Record 200 or 400, and diff the echoed `input_schema`. Then try the dereferenced variant. No session needed, no token cost [INFERRED]. | D1: schema subset |
| P3 | Model and budget acceptance | Budgeted `sessions.create` for agents on `claude-haiku-5-5`, `claude-sonnet-5-5` and `claude-opus-5-5`, with no event sent. Expect no `model_not_budgetable`. Delete right away. | I14 |
| P4 | Travel MCP reachability and tool names | One Haiku agent with 3 `mcp_toolset`s (`default_config: {enabled: true, permission_policy: always_allow}`), `allow_mcp_servers: true`. Prompt: "List the exact names of every tool you have, then call one flight-search tool once for MXP→LIS on a future date." Capture `agent.mcp_tool_use.name` and `mcp_server_name`, and any `session.error` (`mcp_connection_failed_error` / `mcp_authentication_failed_error`). | D3, D6; fills `MCP_SEARCH_TOOLS` |
| P5 | Web tools vs `allowed_hosts` | Same environment as P1. Agent with only `web_search` and `web_fetch`. Prompt: fetch `https://www.example.org`, fetch `https://api.open-meteo.com/v1/forecast?latitude=45.46&longitude=9.19&current=temperature_2m`, and search "Lisbon tram 28". Expect `url_not_allowed` on the first, success on the second, and few or no search results. Repeat once with `unrestricted`. Also try `allowed_domains: [booking.com]` against an `allowed_hosts` without it, and expect a 400 at session create. | D4 |
| P6 | Inter-agent tools | Coordinator (Haiku, `multiagent_20261001`, inline disabled) plus two predefined Haiku subagents A and B. Prompt the coordinator to: (1) list its tool names, (2) delegate to A "list your tool names, then ask the coordinator a question before finishing", (3) ask A to send a note directly to B, (4) after A's end-of-turn report, delegate to A a second time. Inspect `agent.tool_use.name` on every thread stream for `send_to_agent`, `list_agents` or any reply tool, and the `agent.thread_message_*` events. For step (4), record whether a second `session.thread_created` appears for A (a new thread) or A's thread runs again (reused); then `threads.archive` A's idle thread and check that a further delegation to A still works. | D5; thread reuse and archiving (`consumer.superseded_threads`) |
| P7 | Streams, ids, cross-posts | During P6, use raw SSE (`Stream.raw_events`) on the session stream and on each thread stream. Record whether SSE carries `id:` lines. Check that `session.usage` arrives as `event: session.usage` and that `events.stream()` drops it. Diff the ids of `session.thread_status_*` on the primary vs the thread stream. List each thread's history right after `session.thread_created` and check whether it is empty. | §2f dedupe key; I8 |
| P8 | Custom tool round-trip | Coordinator with `submit_plan` calls it. Reply with `is_error: true` and errors, wait for the second call, reply "Plan accepted.", send a duplicate result, and expect no effect. Expect `requires_action` idle, then `running`, then `end_turn`. | §2e |
| P9 | Budget pause and resume | Session with `amount: "3"` ($0.03) and a chatty prompt. Expect `session.thread_status_idle(budget_reached)`, then `session.usage`, then `session.status_idle(budget_reached)`. Send a `user.message` and expect 400. Then `sessions.update(budget=…usage+5)` and expect it to resume. Then `budget=None` and expect `session.updated` with `budget: null`. | §2d budget flow; the spec's `budget_paused` and "Continua con 2 $ in più" |
| P10 | Interrupt and cleanup | Mid-run `user.interrupt` without a thread id. Expect `end_turn` and check the interrupt event's `id` (empty?) and whether its listed copy has `processed_at`. Then archive immediately after idle with `max_retries=0` (race? record the status code: 400 or 409), expect `session.status_terminated`, then `sessions.delete`. Finally `sessions.list(created_at_lt=..., include_archived=True)` and check the session's `metadata`. | I23, I24; `SessionBusyError` mapping; orphan sweep |
| P11 | Skills | `client.skills.create(files=files_from_dir("skills/booking-links"))`. Record the `id` and `latest_version_id` formats (`skver_…`?). Create an agent with `version: "latest"` and with the pinned id, and read the echoed `version`. Then `versions.create` and check whether a new session of the "latest" agent gets the new version. | Skill pinning semantics |
| P12 | `ant` CLI (needs your OK to install) | `brew install anthropics/tap/ant`; `ant --version` (≥1.30). `ant apply --dry-run -v --lock-file /tmp/probe-lock.json profiles/development`. Verify kind inference for `environment.yaml` vs `environments/*.yaml`, that `predefined_agents: [./flights.md]` resolves to `{type: agent, id, version}`, and that `- ./tools/submit_plan.json` is spliced in. Dry-run creates nothing, but it uses credentials and contacts the API to read state [INFERRED]. Then, on a throwaway Haiku coordinator: `agents.update` with a *partial* `multiagent` (only `subagents`), `agents.retrieve`, and diff against the complete object sent at create: did `workflows`/`advisor` keep their stored values (merge) or reset (replacement)? | D2, I21; whether `bootstrap.py` is needed; `multiagent` update semantics (§3) |
| P13 | Usage fields | After P8, `sessions.retrieve(sid).usage`: check whether `list_cost`, `server_tool_use.web_search_requests` and `active_seconds` are populated. `threads.retrieve(tid, session_id=sid).usage.list_cost` per thread. | `cost_cents` source |
| P14 | Custom tool wait: subagents, interrupt, cache | Haiku coordinator (`multiagent_20261001`, inline disabled) with a stand-in custom tool `ask_traveller`, plus one predefined Haiku worker with only `bash`; two sessions capped at 25c each. Both start with "delegate to the worker six `sleep 30` bash calls, then right away call `ask_traveller`". **Session 1:** leave the call unanswered 240 s (the choice cards' timeout), polling the session's and every thread's status, then answer with `user.custom_tool_result` and follow to the final idle. From the histories: the worker thread's events and statuses against the call and the answer (does it keep working while the coordinator waits?), whether the coordinator runs during the wait, and the coordinator's last request before and first request after the wait (`span.model_request_end.model_usage`: `cache_read_input_tokens` vs the earlier prompt), plus the primary thread's `usage.cache_creation` split (`ephemeral_5m` vs `ephemeral_1h`). **Session 2:** 20 s into the wait, `user.interrupt` without a thread id: the send's HTTP outcome, the events that follow, the statuses, whether the platform answers the pending call itself; then a `user.message` (400 if the call still blocks it?) and a late `user.custom_tool_result`. | Choice cards (`docs/superpowers/specs/2026-10-18-plan-creation-ux-design.md` §2, not on main yet): whether the research overlaps the pause, how "Interrompi" closes a pending choice, and whether a 4-minute pause resumes on a warm cache |

---

## 5. Cost levers

Researched 2026-10-12, offline: no API call, no session, no MCP. It answers one question: which settings make a Managed Agents plan cheaper, and what did the first real dev eval run (5 sessions, every one stopped at the 60c budget before wave 2) show about where the money goes. Tags as in the legend; **verified** means read in the SDK or the official docs, **inferred** is my own reasoning.

### What a session costs (measured on the Lisbon session of that run)

Source: the session report of the run (`scripts/session_report.py`, thread `usage` and `list_cost` from the API). I fitted the per-thread `list_cost` to the token counts: the Sonnet 5.5 coordinator matches the published rates to the cent ($2 in, $2.50 5m cache write, $0.10 cache read, $10 out), and the three Haiku 5.5 threads match **only** if every request is priced at Haiku's over-100k tier ($0.625 write, $0.05 read, $2.50 out; activities 19.2c vs 19c reported, flights 15.3c vs 15c, lodging 13.3c vs 13c) [INFERRED from the fit; the ≤100k rates would give 4 to 8c per thread]. Web search is $0.01 each [DOCS https://platform.claude.com/docs/en/managed-agents/budgets], web fetch has no charge [DOCS https://platform.claude.com/docs/en/about-claude/pricing].

| Component | Cents | Share of 62c | What drives it |
|---|---:|---:|---|
| Cache writes | 26.1 | 42% | every new tool result and message is written once: each web_search result is 20k to 45k characters |
| Cache reads | 13.0 | 21% | the whole context is re-read at every request: results stay for the rest of the thread |
| Output (thinking included) | 12.5 | 20% | Haiku threads 9k to 16k output tokens each; one request wrote 10.6k tokens (a 7.6k-character file after long thinking) |
| Web search fee | 10.0 | 16% | 10 searches |
| Runtime | 0.2 | 0.4% | 105 s at $0.08/hour |

One web_search therefore costs about 2c: 1c fee plus about 9k tokens written once and re-read by every later request (10 to 15 requests left in the thread). A 3.3k-token skill file read at the start costs about 0.4c (written once, re-read 9 to 14 times); slimming all the skill loads is worth about 3 to 4c per plan. The bigger levers are the searches, the fetches, the number of requests and the thinking.

### Knobs that exist (verified)

| Knob | Where | Effect | Used |
|---|---|---|---|
| `model.effort` (`low`, `medium`, `high`, `xhigh`, `max`) | agent `model: {id, effort}`; in `ant` frontmatter `model: {id: ..., effort: low}` [SDK types/beta/beta_managed_agents_model_config_params.py] [DOCS https://platform.claude.com/docs/en/managed-agents/agent-setup] | The only thinking control: "affects all tokens", thinking included; lower effort also means fewer and terser tool calls. Defaults: Haiku 5.5 and Opus 5.5 `medium`, Sonnet 5.5 `high`. Docs call `low` the choice "such as subagents" [DOCS https://platform.claude.com/docs/en/build-with-claude/effort]. Haiku 5.5 at `low` is "more likely to skip a search, stop early, or skip a check" [DOCS https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5] | development: coordinator `medium`, subagents `low`; production: all `medium` |
| `web_fetch.max_content_tokens` | the `web_fetch` entry of `agent_toolset_20260401.configs`, positive integer [SDK types/beta/beta_managed_agents_web_fetch_tool_config_params.py] [DOCS https://platform.claude.com/docs/en/managed-agents/tools-web-restrictions] | Caps the page text one call puts in the context; not for PDFs. In a multiagent session a thread uses its own tool config's value first | development 3,000, production 6,000 (pages in the run were 1.8k to 4.5k tokens, by characters / 4) |
| `web_search` / `web_fetch` `allowed_domains` or `blocked_domains` (1 to 64 hosts, one of the two) | same entries [DOCS tools-web-restrictions] | Narrows the sources. It does not shorten a result and the trips go everywhere, so a list would cost coverage; not used | no |
| `web_search.user_location` | same entry | Localises results; the destination changes per request | no |
| Tool outputs above 100,000 characters (about 25,000 tokens) are written to a file in the sandbox and the model gets a truncated preview | platform behaviour [DOCS https://platform.claude.com/docs/en/managed-agents/tools] | A built-in ceiling per result; the run's biggest result was 37k characters, below it | n/a |
| `default_config.enabled: false` and per-tool `enabled` | toolset, MCP toolsets | Fewer tool definitions in every request | already used by every template |
| Per-agent and per-session budget `max_list_cost` | session create [DOCS budgets] | A stop, not a saving; owned by the backend (`SESSION_BUDGET_CENTS`) | profile numbers only |

### Knobs that do not exist (verified absent)

| Wanted | Finding |
|---|---|
| `max_uses` on web_search | Not available on the Managed Agents toolset: "`max_uses`, `citations`, and `cache_control` are not available on the toolset" [DOCS tools-web-restrictions]. The SDK type has no such field. **The search cap is a prompt rule** (`web_search_cap`, now also `web_fetch_cap`); nothing enforces it. |
| A result-count or snippet-length limit for web_search | None in the SDK type [SDK types/beta/beta_managed_agents_web_search_tool_config_params.py] or the docs. |
| Disabling thinking | The agent `model` object has `effort`, `speed` and `inference_geo` only [SDK types/beta/beta_managed_agents_model_config_params.py]; `agent_create_params` has no `thinking` field. `thinking: {"type": "disabled"}` exists on the Messages API for Haiku 5.5 (at `high` effort or below), but Managed Agents does not expose it. |
| Compaction or context editing (clearing old tool results) | Automatic only: "The harness supports built-in prompt caching, compaction, and other performance optimizations" [DOCS https://platform.claude.com/docs/en/managed-agents/overview]; the session emits `agent.thread_context_compacted` when history "was compacted to fit the context window" [DOCS https://platform.claude.com/docs/en/managed-agents/reference]. No agent, session or tool parameter configures it, and the SDK's Managed Agents params contain no `context_management` or `compaction` field (grep of `types/beta/agent_*params.py`, `session_*params.py`, `beta_managed_agents_*`). It happens near the context limit, far above the 70k to 140k contexts of these runs, so it does not help. |
| Cache TTL (5 minutes or 1 hour) | Usage reports cache writes split by TTL [SDK types/beta/beta_managed_agents_cache_creation_usage.py] but no parameter chooses it. Every write of the P14 session was a 5-minute write [PROBE P14 docs/probes/2026-10-18.md] (§2e). |
| Per-thread or per-subagent budget | One budget per session shared by all threads [DOCS budgets]. |

Changing a thread's effort between requests would invalidate its prompt cache [DOCS effort], so the effort is fixed per agent in the template and never changed in a session.

### What the repository applies

- `agents/profiles.yaml`: development `web_search_cap` 5 to 3, `web_fetch_cap` 4, `web_fetch_max_content_tokens` 3000, `efforts` (coordinator `medium`, subagents `low`); production keeps `web_search_cap` 12 (no tool-level knob makes it cheaper), `web_fetch_cap` 8, `web_fetch_max_content_tokens` 6000, all `medium`. `scripts/render_profiles.py` validates the new keys and the rendered `model` object and `max_content_tokens`.
- Prompts: each subagent has a "Cost rules" section (MCP first and no web search when it returned enough, one search per question and never a repeat, the time read once, one geocode command for all properties, write the file as soon as there are enough options and do not read it back); the coordinator may not re-delegate for a thin or estimated result and reads each file once; the plan's notes stay short because plan output is the coordinator's biggest cost.
- Skills: each `SKILL.md` is a core of at most 6,500 characters (about 1,600 tokens) that says when to read which `references/*.md`; the old 12.4k, 8.5k and 16.4k character files were 3.3k, 2.2k and 4k tokens each, loaded whole by every agent at the start and re-read at every request. `schemas/<agent>.json` is read right before writing by the agent without bash and only after a rejection by the others. `skills/test_skill_packaging.py` enforces the size and that every reference is pointed at.

### Measured offline: `session_report.py --static`, profile `development`

Floor = system prompt + custom tool schema + skill descriptions, paid by every request; "after loads" adds the files the agent is expected to read. Built-in tool and MCP schemas are not measurable offline (the live first-request contexts were 7k to 20k tokens).

| agent | floor before | floor after | after loads before | after loads after |
|---|---:|---:|---:|---:|
| coordinator | ~7,193 | ~7,398 | ~18,475 | ~16,757 |
| activities | ~1,532 | ~1,851 | ~6,598 | ~5,385 |
| flights | ~1,562 | ~1,884 | ~8,648 | ~4,280 |
| lodging | ~1,675 | ~2,005 | ~8,733 | ~4,400 |
| transport | ~1,720 | ~2,007 | ~8,650 | ~4,402 |

The floor grows by 200 to 330 tokens per agent (the cost rules); the skill loads shrink by 1.2k (activities) to 4.4k (flights) tokens, 1.7k for the coordinator, and they are re-read at every request. The "after loads" column counts the schema file for the activities agent only (it has no validator) and counts `travel-research-rules/SKILL.md` for the coordinator although its prompt now says it need not read it.

### Per-plan estimate, development profile (inferred, not measured)

Same request as the Lisbon session. Rates as fitted above; web results ~10k tokens written per search and ~3.3k per capped fetch; request counts and outputs from the run, with the contingency in the last column for retries and rewrites. These are my assumptions: a real run is the only measurement.

| Part | Before | After | Assumptions for "after" |
|---|---:|---:|---|
| flights | 15c | 5 to 8c | MCPs called in one turn; one search plus one fetch only when they return nothing |
| lodging | 13c | 5 to 8c | one geocode command; web only if Expedia gave fewer than 3 options |
| activities, first task | 19c | 9 to 13c | 3 searches and 4 capped fetches instead of 5 and 5; short skill; no read-back |
| activities, follow-up | 3c | 2 to 3c | no new search |
| transport | about 13c (not reached) | 8 to 12c | 3 searches and 4 fetches |
| coordinator | 14c up to wave 1, about 35c in all | 25 to 33c | no re-delegation, medium effort, shorter plan text, skills read late |
| **Total** | **about 95 to 105c** | **about 55 to 85c, central 71c** | |

So the 60c development budget was too small for a full plan before this change (about 98c) and is still tight after it. The coordinator is the largest line (about 30c): composing the plan is 8k output tokens at Sonnet's $10/MTok plus the files it reads. Two decisions are left to Michele and were not applied: moving the development coordinator to `claude-haiku-5-5` in `agents/profiles.yaml` (about 21c less, total about 50c; plan quality is likely to drop), or raising the development `SESSION_BUDGET_CENTS` to about 90 (backend setting). The eval ceiling in `evals/README.md` (5 plans at 60c) would move with it.

### Risks of these changes

- `effort: low` on Haiku 5.5 can skip a search, stop early or skip a check [DOCS prompting-claude-haiku-5-5]. The subagent prompts say the turn ends only after the file and the two-line reply; the evals will show whether the quality holds. If it does not, set the affected agent to `medium` in `agents/profiles.yaml` and re-render.
- `max_content_tokens` truncates a long page (the docs do not say where), so a price or an opening day can be lost (a 3,000 cap is below roughly half of the pages seen in the run). The activities prompt asks for a warning when prices and hours were not checked.
- The search and fetch caps are advisory: Haiku can overshoot them. The measure is the next live report (`web searches` per thread).

