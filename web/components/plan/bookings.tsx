import { AgentRoundel } from "@/components/ui/agent";
import { LinkButton } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { cx } from "@/components/ui/cx";
import { Icon } from "@/components/ui/icon";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import type { BookingDeadline } from "@/lib/booking-dates";
import { formatDateTime, HOME_TIMEZONE } from "@/lib/format";
import type { LinkCheck, LinkHealthMap } from "@/lib/schemas/api";
import type { PlanBooking, Price } from "@/lib/schemas/generated/plan";

import { LiveDatePair } from "./live-date-pair";
import {
  bookingAction,
  bookingCategory,
  bookingLine,
  CATEGORY_LABELS,
  formatPrice,
  hostLabel,
  planUrl,
  safeHttpUrl,
  type BookingAction,
  type PlanUrl,
} from "./plan-model";

/** A quiet link to another site: ink, underlined, new tab, `rel="noopener noreferrer"`. For
 * information (a price's source, a stop's page), never for booking. */
export function QuietExternalLink({ href, children, className }: { href: string; children: string; className?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cx(
        "inline-flex items-baseline gap-1 rounded-xs text-ink underline decoration-rule-strong underline-offset-[0.2em]",
        "transition-[text-decoration-color] duration-(--duration-hover) hover:decoration-ink [overflow-wrap:anywhere]",
        className,
      )}
    >
      {children}
      <Icon name="arrow-square-out" size={12} className="relative top-px self-center" />
      <VisuallyHidden> (si apre in una nuova scheda)</VisuallyHidden>
    </a>
  );
}

/** "Expedia" when the source is the booking's own allowed site, else its host ("oceanario.pt"). */
function sourceName(source: URL, check: LinkCheck | null): string {
  if (check?.allowed && check.label && check.host === source.hostname) return check.label;
  return hostLabel(source);
}

/** The name the price line shows for a source that is a page or a homepage, else null. */
function sourceLabel(where: PlanUrl, check: LinkCheck | null): string | null {
  if (where.kind === "homepage") return where.host;
  if (where.kind !== "link") return null;
  const parsed = safeHttpUrl(where.href);
  return parsed ? sourceName(parsed, check) : where.host;
}

/** The warning glyph and the title of a state with no button: ink, semibold. */
function WarningTitle({ children }: { children: string }) {
  return (
    <p className="flex items-center gap-1.5 font-semibold text-ink">
      <Icon name="warning" size={14} />
      <span>{children}</span>
    </p>
  );
}

/** Price, its status as a word and its provenance: "812,00 € [verificato] Fonte expedia.it,
 * letto il 12 ott 2026, 12:01". */
function PriceLine({ price, check, where }: { price: Price | null; check: LinkCheck | null; where: PlanUrl }) {
  if (!price) return <p className="mt-1 text-small text-ink-2">Prezzo non indicato</p>;
  const source = safeHttpUrl(price.source_url);
  return (
    <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-small text-ink-2">
      <span className="font-semibold text-ink">{formatPrice(price)}</span>
      <Chip>{price.status === "verified" ? "verificato" : "stimato"}</Chip>
      <span className="min-w-0">
        Fonte{" "}
        {where.kind === "homepage" ? (
          <QuietExternalLink href={where.href}>{`sito di ${where.host}`}</QuietExternalLink>
        ) : where.kind === "missing" ? (
          <span className="[overflow-wrap:anywhere]">{where.host ?? price.source_url} (pagina non trovata)</span>
        ) : source ? (
          <QuietExternalLink href={price.source_url}>{sourceName(source, check)}</QuietExternalLink>
        ) : (
          <span className="[overflow-wrap:anywhere]">{price.source_url}</span>
        )}
        , letto il <time dateTime={price.retrieved_at}>{formatDateTime(price.retrieved_at)}</time>
      </span>
    </p>
  );
}

/** The action side of a booking: "Prenota su <sito>" only when the link passed the backend's
 * allowlist; otherwise the link is plain text, never an anchor. */
function ActionSide({
  action,
  alternative,
  vendor,
  phone,
  source,
  sourceName: sourceNameText,
}: {
  action: BookingAction;
  alternative: boolean;
  vendor: string | null;
  phone: string | null;
  /** Where the price was read: the nearest thing to "the supplier's own site" a booking without a
   * link has. Named as text (the price line above links it for information), never a button. */
  source: PlanUrl;
  /** The name the price line shows for a source that is alive (a page or a homepage), else null. */
  sourceName: string | null;
}) {
  if (action.kind === "button") {
    const button = (
      <LinkButton
        href={action.href}
        external
        variant={alternative ? "secondary" : "primary"}
        size={alternative ? "sm" : "md"}
        className={alternative ? "lg:w-full" : "w-full"}
      >
        {alternative ? `Vedi su ${action.site}` : `Prenota su ${action.site}`}
      </LinkButton>
    );
    if (!action.fallback) return button;
    // The link was dead: the button goes to the site's home, so the search starts over.
    return (
      <div className="min-w-0 flex-1">
        {button}
        <p className="mt-1.5 text-micro text-ink-2">{`Porta alla home di ${action.site}: la ricerca va rifatta.`}</p>
      </div>
    );
  }
  if (action.kind === "missing") {
    const hasWay = source.kind === "link" || source.kind === "homepage" || Boolean(vendor) || Boolean(phone);
    // The source is named, never linked, here: it has not passed the booking allowlist, and when it
    // is the dead link itself its homepage is the one the backend refused (the price line above
    // links it for information).
    const sourceText =
      source.kind === "link"
        ? `Cerca l'offerta su ${sourceNameText ?? source.host}`
        : source.kind === "homepage"
          ? `Cerca l'offerta sul sito di ${source.host}`
          : null;
    return (
      <div className="min-w-0 text-meta text-ink-2" data-link-text="">
        <WarningTitle>Pagina di prenotazione non trovata</WarningTitle>
        <p>Il link del piano non apre nessuna pagina.</p>
        {sourceText ? <p className="mt-1 [overflow-wrap:anywhere]">{sourceText}</p> : null}
        {vendor ? <p>{`Prenota direttamente con ${vendor}.`}</p> : null}
        <PhoneLine phone={phone} />
        {hasWay ? null : <p className="mt-1">Cerca il servizio sul sito del fornitore.</p>}
        <p className="mt-1.5 line-clamp-3 text-micro [overflow-wrap:anywhere]">
          Indirizzo originale: <span className="select-all">{action.text}</span>
        </p>
      </div>
    );
  }
  if (action.kind === "text") {
    return (
      <div className="min-w-0 text-meta text-ink-2" data-link-text="">
        <WarningTitle>Link non verificato</WarningTitle>
        <p>Il sito non è tra quelli controllati, quindi il link resta testo.</p>
        <p className="mt-1 line-clamp-3 text-micro select-all [overflow-wrap:anywhere]">{action.text}</p>
      </div>
    );
  }
  return (
    <div className="min-w-0 text-meta text-ink-2">
      <p>
        Nessun link di prenotazione.{" "}
        {source.kind === "link" || source.kind === "homepage" ? (
          <>
            {vendor ? `Prenota sul sito di ${vendor}: ` : "Prenota sul sito: "}
            <span className="font-semibold text-ink [overflow-wrap:anywhere]">{source.host}</span>
          </>
        ) : vendor ? (
          `Prenota direttamente con ${vendor}.`
        ) : null}
      </p>
      <PhoneLine phone={phone} />
    </div>
  );
}

/** "Telefono +351 ...", the number a `tel:` link (the only anchor of a booking without a usable
 * link); nothing without a phone. */
function PhoneLine({ phone }: { phone: string | null }) {
  if (!phone) return null;
  return (
    <p>
      Telefono{" "}
      <a href={`tel:${phone.replace(/[^\d+]/g, "")}`} className="rounded-xs text-ink underline underline-offset-[0.2em]">
        {phone}
      </a>
    </p>
  );
}

const NO_HEALTH: LinkHealthMap = {};

interface BookingRowProps {
  booking: PlanBooking;
  /** The backend's verdict on `booking.link` (PlanDetail.booking_links / .alternative_links). */
  check: LinkCheck | null;
  /** The link check's verdicts by URL (PlanDetail.link_health); only `dead` changes the row. */
  health?: LinkHealthMap;
  /** The "Prenota entro" side, decided by the caller (lib/booking-dates `bookingDeadline` for
   * the plan's bookings, `alternativeDeadline` for alternatives). */
  deadline: BookingDeadline;
  /** The trip's time zone (plan.timezone): the clock of "Quando". */
  timeZone: string;
  /** The booking starts from home: "Quando" leads with the clock at home (see DatePair). */
  startsAtHome?: boolean;
  /** The words after the trip's clock when it is the second line ("a Lisbona"). */
  tripLabel?: string | null;
  /** A discarded alternative: compact dates, a secondary "Vedi su <sito>". */
  alternative?: boolean;
  id?: string;
}

/**
 * One booking as a row of the finished plan (DESIGN.md, Layout): roundel, kind, title, price
 * with status and source | "Prenota entro" and "Quando" (DatePair, always both, always
 * labelled) | "Prenota su <sito>". On the phone the three stack; from 1080 px they sit side by
 * side (1.3fr 1.4fr 240px).
 */
export function BookingRow({ booking, check, health = NO_HEALTH, deadline, timeZone, startsAtHome = false, tripLabel = null, alternative = false, id }: BookingRowProps) {
  const line = bookingLine(booking, check);
  const action = bookingAction(booking.link, check, health);
  // One verdict for the price's source, shared by the price line and the action side.
  const sourceVerdict = planUrl(booking.price?.source_url, health);
  return (
    <li
      id={id}
      className={cx(
        "grid scroll-mt-24 gap-3 border-t border-rule py-3.5 first:border-t-0",
        alternative
          ? "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1.4fr)_240px] lg:items-start lg:gap-6"
          : "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1.4fr)_240px] lg:items-start lg:gap-6 lg:py-5",
      )}
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <AgentRoundel agent={line} size="sm" className="mt-0.5" />
        <div className="min-w-0">
          <p className="text-meta text-ink-2">{CATEGORY_LABELS[bookingCategory(booking, check)]}</p>
          <h3 className="text-body font-semibold [overflow-wrap:anywhere]">{booking.title}</h3>
          <PriceLine price={booking.price} check={check} where={sourceVerdict} />
          {booking.notes ? (
            <p className="mt-1.5 text-meta whitespace-pre-line text-ink-2 [overflow-wrap:anywhere]">{booking.notes}</p>
          ) : null}
        </div>
      </div>
      <div className="min-w-0">
        <LiveDatePair
          deadline={deadline}
          scheduledFor={booking.scheduled_for}
          timeZone={timeZone}
          deadlineTimeZone={HOME_TIMEZONE}
          startsAtHome={startsAtHome}
          tripLabel={tripLabel}
          variant={alternative ? "compact" : "fields"}
        />
        {booking.book_by_reason ? (
          <p className="mt-1.5 text-meta text-ink-2 [overflow-wrap:anywhere]">{booking.book_by_reason}</p>
        ) : null}
      </div>
      <div className="flex min-w-0">
        <ActionSide
          action={action}
          alternative={alternative}
          vendor={booking.vendor?.trim() || null}
          phone={booking.phone?.trim() || null}
          source={sourceVerdict}
          sourceName={sourceLabel(sourceVerdict, check)}
        />
      </div>
    </li>
  );
}
