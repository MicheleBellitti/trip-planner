import { Disclosure } from "@/components/ui/disclosure";
import { AGENT_LABELS } from "@/lib/plan-events/labels";
import type { EvalAgentVersions } from "@/lib/schemas/api";
import type { AgentName } from "@/lib/schemas/generated/ui-event";

const MONO = "font-[ui-monospace,SFMono-Regular,Menlo,Consolas,monospace] text-micro break-all";

/** Agent versions are small integers ("v1"); a skill's is an opaque id ("skver_...") shown as it is. */
function versionText(version: unknown): string | null {
  if (typeof version === "number") return `v${version}`;
  if (typeof version !== "string" || version === "") return null;
  return /^\d+$/.test(version) ? `v${version}` : version;
}

function Row({ label, id, version }: { label: string; id: string; version?: unknown }) {
  const text = versionText(version);
  return (
    <div className="grid gap-x-4 gap-y-0.5 py-2 sm:grid-cols-[11rem_minmax(0,1fr)]">
      <dt className="text-small text-ink-2">{label}</dt>
      <dd className="min-w-0 text-ink">
        <code className={MONO}>{id}</code>
        {text ? <span className="ml-2 text-meta text-ink-2">{text}</span> : null}
      </dd>
    </div>
  );
}

/**
 * The Managed Agents a run used, in a closed section: the coordinator, the four subagents and the
 * skills with their ids and versions, the environment and the lockfile's digest. It answers "what
 * exactly did this run measure", which the commit alone does not (the lockfile pins the agents).
 */
export function AgentVersions({ versions, className }: { versions: EvalAgentVersions | null; className?: string }) {
  if (versions === null) {
    return (
      <p className={className}>
        <span className="text-small text-ink-2">Questa valutazione non ha registrato le versioni degli agenti.</span>
      </p>
    );
  }
  const subagents = Object.entries(versions.subagents);
  const skills = Object.entries(versions.skills);
  return (
    <Disclosure variant="section" summary="Versioni degli agenti" className={className}>
      <dl className="divide-y divide-rule">
        {versions.coordinator ? (
          <Row label={AGENT_LABELS.coordinator} id={versions.coordinator.id} version={versions.coordinator.version} />
        ) : null}
        {subagents.map(([name, agent]) => (
          <Row key={name} label={AGENT_LABELS[name as AgentName] ?? name} id={agent.id} version={agent.version} />
        ))}
        {skills.map(([name, skill]) => (
          <Row key={name} label={`Skill ${name}`} id={skill.id} version={skill.version} />
        ))}
        {versions.environment_id ? <Row label="Ambiente" id={versions.environment_id} /> : null}
        {versions.lockfile_sha256 ? <Row label="Lockfile (sha256)" id={versions.lockfile_sha256} /> : null}
      </dl>
    </Disclosure>
  );
}
