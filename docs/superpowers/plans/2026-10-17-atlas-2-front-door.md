# Atlas front door (step 2 of 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Atlas a public front door:
- the landing at `/` (hero, legend and line map, "Come funziona" with three real component samples, closing, footer, public header);
- the plans list moved to `/plans`;
- returning signed-in visitors skipping the landing.

**Architecture:**
- The landing is a prerendered Server Component page built from `components/landing/*`. Its only client JavaScript is the theme toggle and `next/link`. The motion is CSS with `motion-safe:` variants.
- `ROUTES.plans` becomes `"/plans"`. Every link already reads it, since step 1 added `lib/routes.ts`.
- `lib/returning.ts` owns a localStorage mark. The API client sets the mark after any authenticated 2xx and clears it on a 401. An inline script, first in the landing's markup, reads the mark and calls `location.replace("/plans")` before paint, unless the visitor came from a page of this site.
- `/demo` is step 3, so `DEMO_READY = false` gates every demo call to action.

**Tech Stack:** Next.js 16.4 App Router (Cache Components, static prerender), React 19.3, Tailwind 4, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-14-atlas-brand-design.md`, section 2 and section 8, step 2. Approved landing mockup: `.superpowers/landing/landing-v1.html` (local, git-ignored).

**Michele's decisions on the mockup (2026-10-17):**
1. "Accedi" appears only in the header and in the closing section, so the hero's only action is the demo.
2. On the phone the map comes before the legend.
3. The motion is as in the mockup: one choreographed moment (the hero map). The "Come funziona" stations do not animate.

## Global Constraints

- Work in `web/` on branch `feat/atlas-front-door`, cut from `origin/main` at `4f5b4df`.
- Read the guide in `web/node_modules/next/dist/docs/` before writing Next-specific code.
- No new runtime dependency. No backend, TripTracker, auth or contract change.
- On-screen text is Italian in sentence case, with no em dash. The middle dot appears only inside backend-style tool titles, as in the samples. Code and comments are English.
- The name and the tagline are read from `BRAND_NAME` and `BRAND_TAGLINE` only. Paths are read from `ROUTES` only: the invariants forbid a literal `href="/"`.
- Amber is drawn only by `DatePair`. The No AI Chrome Rule holds (`components/ui/invariants.test.ts`). The tokens in `web/DESIGN.md` and `globals.css` change together.
- **Never hand-write booking URLs** (CLAUDE.md contract rule 4). The landing's booking sample is an illustration: its "Prenota su Expedia" is not a link.
- Every animation is `motion-safe:` only. Under reduced motion the final state shows, still.
- `/plans/[id]` first-load JS must not grow (192.2 KB gzip). `/` should come in under `/plans`.
- Check every new screen at 393 px and at desktop width, dark and light. Run one impeccable critique round on `/`. A fresh reviewer reviews the whole branch. Then open the PR.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A signed-in visitor opening `atlas.bellittim.com` from a bookmark** lands on `/plans`. If they arrive from a page of this site, the landing shows. A browser without the mark, or with storage blocked, sees the landing. Test: Task 1, `lib/returning.test.ts`; Task 6, browser check.
2. **A session that expired** clears the mark on the first 401, so the next visit to `/` shows the landing instead of bouncing to the login. Test: Task 1, `lib/api.test.ts`.
3. **No button leads to a 404** while `/demo` does not exist. Test: Task 2 and Task 4, `components/landing/landing.test.tsx` (no `/demo` link with `DEMO_READY = false`; both demo calls to action present with `demoReady`).
4. **A screen reader on the landing** hears each sample as one sentence, never as a broken form or a dead button. Test: Task 3, `landing.test.tsx`.
5. **Old bookmarks and links to the list:** `/` from a signed-in browser goes to `/plans`. "Torna ai piani" and the in-app lockup go to `/plans`. Test: Task 1 (ROUTES), the existing `app-header.test.tsx`, and the Task 6 browser check.

---

### Task 1: Routes, the move to `/plans`, returning visitors

**Files:**
- Modify: `web/lib/routes.ts`
- Create: `web/lib/returning.ts`, `web/lib/returning.test.ts`
- Modify: `web/lib/api.ts`, `web/lib/api.test.ts`
- Create: `web/app/plans/page.tsx` (the list, moved here from `web/app/page.tsx`)
- Create: `web/components/landing/skip-landing-script.tsx`, `web/components/landing/public-header.tsx`, `web/components/landing/landing.test.tsx`
- Modify: `web/app/page.tsx` (the landing; Tasks 2–4 fill it in)

**Interfaces:**
- Produces, in `web/lib/routes.ts`:
  - `ROUTES = { home: "/", plans: "/plans", newPlan: "/new", evals: "/evals", demo: "/demo" }`
  - `DEMO_READY = false`
- Produces, in `web/lib/returning.ts`:
  - `SIGNED_IN_KEY`
  - `markSignedIn()`
  - `markSignedOut()`
  - `SKIP_LANDING_DECISION`: ES5 function source, `(storage, referrer, origin) => string | null`
  - `SKIP_LANDING_BOOTSTRAP`
- Produces, in `web/components/landing/`:
  - `SkipLandingScript()`
  - `PublicHeader()`

- [ ] **Step 1: Write the failing tests**

Create `web/lib/returning.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { markSignedIn, markSignedOut, SIGNED_IN_KEY, SKIP_LANDING_BOOTSTRAP, SKIP_LANDING_DECISION } from "./returning";

type Decide = (storage: Pick<Storage, "getItem">, referrer: string, origin: string) => string | null;
// The same source the inline script runs.
const decide = new Function(`return (${SKIP_LANDING_DECISION})`)() as Decide;
const ORIGIN = "https://atlas.bellittim.com";
const marked = { getItem: () => "1" };
const unmarked = { getItem: () => null };

afterEach(() => localStorage.clear());

describe("the landing skip", () => {
  it("sends a signed-in browser arriving from outside to the plans", () => {
    expect(decide(marked, "", ORIGIN)).toBe("/plans");
    expect(decide(marked, "https://viaggi.bellittim.com/accedi", ORIGIN)).toBe("/plans");
  });

  it("shows the landing to a signed-in browser that came from a page of this site", () => {
    expect(decide(marked, `${ORIGIN}/plans/6f1c2a7e`, ORIGIN)).toBeNull();
  });

  it("shows the landing without the mark", () => {
    expect(decide(unmarked, "", ORIGIN)).toBeNull();
  });

  it("fails safe to the landing when storage throws", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
    };
    expect(decide(blocked, "", ORIGIN)).toBeNull();
  });

  it("treats an unreadable referrer as outside", () => {
    expect(decide(marked, "not a url", ORIGIN)).toBe("/plans");
  });

  it("runs the decision inside a script that never throws", () => {
    expect(SKIP_LANDING_BOOTSTRAP).toContain(SKIP_LANDING_DECISION);
    expect(SKIP_LANDING_BOOTSTRAP.startsWith("(function(){try{")).toBe(true);
  });
});

describe("the mark", () => {
  it("is set and cleared", () => {
    markSignedIn();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBe("1");
    markSignedOut();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBeNull();
  });

  it("stays silent when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(markSignedIn).not.toThrow();
    expect(markSignedOut).not.toThrow();
  });
});
```

In `web/lib/api.test.ts`:
- Add `afterEach` to the vitest import.
- Add `import { SIGNED_IN_KEY } from "./returning";`.
- Append:

```ts
describe("the returning-visitor mark", () => {
  afterEach(() => localStorage.clear());

  it("is set by a successful authenticated call", async () => {
    const { api } = client(json(200, { plans: [] }));
    await api.listPlans();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBe("1");
  });

  it("is not set by the health check, which needs no sign-in", async () => {
    const { api } = client(json(200, HEALTH_OK));
    await api.health();
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBeNull();
  });

  it("is cleared by a 401, so an expired session sees the landing next time", async () => {
    localStorage.setItem(SIGNED_IN_KEY, "1");
    const { api } = client(json(401, envelope("not_authenticated", "Accedi a TripTracker per usare il planner.")));
    await failure(api.listPlans());
    expect(localStorage.getItem(SIGNED_IN_KEY)).toBeNull();
  });
});
```

(`HEALTH_OK` is a valid `HealthResponseSchema` body. Read `lib/schemas/api.ts` and define it once at the top of the file.)

Create `web/components/landing/landing.test.tsx`:

```tsx
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LandingPage from "@/app/page";
import { SKIP_LANDING_BOOTSTRAP } from "@/lib/returning";
import { ROUTES } from "@/lib/routes";

vi.mock("@/components/ui/theme-toggle", () => ({ ThemeToggle: () => <button type="button">Tema</button> }));

afterEach(cleanup);

describe("the landing", () => {
  it("runs the landing skip before anything else on the page", () => {
    const { container } = render(<LandingPage />);
    const first = container.firstElementChild;
    expect(first?.tagName).toBe("SCRIPT");
    expect(first?.innerHTML).toBe(SKIP_LANDING_BOOTSTRAP);
  });

  it("has a public header: the lockup home, how it works, sign in to the plans", () => {
    render(<LandingPage />);
    const header = screen.getByRole("banner");
    expect(within(header).getByRole("link", { name: "Atlas" }).getAttribute("href")).toBe(ROUTES.home);
    expect(within(header).getByRole("link", { name: "Come funziona" }).getAttribute("href")).toBe("#come-funziona");
    expect(within(header).getByRole("link", { name: "Accedi" }).getAttribute("href")).toBe(ROUTES.plans);
  });
});
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `npx vitest run lib/returning.test.ts lib/api.test.ts components/landing/landing.test.tsx`

Expected: FAIL.
- `./returning` cannot be resolved.
- The mark tests in `api.test.ts` fail, because the mark is never set.
- The landing test renders today's plans page, which has no `banner` with "Come funziona".

- [ ] **Step 3: Routes**

Replace `web/lib/routes.ts` with:

```ts
/**
 * Where the app's pages live, so no link spells a path by hand (components/ui/invariants.test.ts).
 * The brand spec (docs/superpowers/specs/2026-10-14-atlas-brand-design.md) gives "/" to the public
 * landing and the plans list to "/plans" (step 2), and adds the public demo at "/demo" (step 3).
 */
export const ROUTES = {
  home: "/",
  plans: "/plans",
  newPlan: "/new",
  evals: "/evals",
  demo: "/demo",
} as const;

/** The public demo run (step 3) does not exist yet. Until it does, the landing offers "Scopri come
 * funziona" instead of "Guarda una corsa", so no button leads to a 404. Step 3 builds /demo and
 * flips this. */
export const DEMO_READY = false;
```

- [ ] **Step 4: The returning mark**

Create `web/lib/returning.ts`:

```ts
/**
 * Returning visitors skip the landing (brand spec, "Returning visitors skip the landing"). The API
 * client marks the browser after a successful authenticated call and clears the mark on a 401. An
 * inline script on "/" (components/landing/skip-landing-script.tsx) reads it before paint. The
 * mark holds no personal data, and every storage access fails safe to "show the landing".
 */
import { ROUTES } from "./routes";

export const SIGNED_IN_KEY = "atlas-signed-in";

export function markSignedIn(): void {
  try {
    localStorage.setItem(SIGNED_IN_KEY, "1");
  } catch {
    // Storage blocked: the landing simply shows next time.
  }
}

export function markSignedOut(): void {
  try {
    localStorage.removeItem(SIGNED_IN_KEY);
  } catch {
    // Storage blocked: nothing was stored either.
  }
}

/** The decision, as ES5 source so the inline script and the tests run the same code. It returns
 * the plans' path when the mark is set and the visitor did not come from a page of this site (a
 * bookmark, a typed URL, the login coming back), else null. */
export const SKIP_LANDING_DECISION = `function(storage,referrer,origin){try{if(storage.getItem(${JSON.stringify(
  SIGNED_IN_KEY,
)})!=="1")return null;var from="";try{from=referrer?new URL(referrer).origin:""}catch(e){}return from===origin?null:${JSON.stringify(
  ROUTES.plans,
)}}catch(e){return null}}`;

/** The inline script on "/": run the decision and leave before the landing paints. Silent when
 * storage cannot even be reached. */
export const SKIP_LANDING_BOOTSTRAP = `(function(){try{var to=(${SKIP_LANDING_DECISION})(window.localStorage,document.referrer,location.origin);if(to)location.replace(to)}catch(e){}})()`;
```

- [ ] **Step 5: Mark from the API client**

In `web/lib/api.ts`:
- Add `import { markSignedIn, markSignedOut } from "./returning";`.
- In `errorFromResponse`, inside `if (status === 401) {`, add `markSignedOut();` as the first line.
- In `send`, right after `if (!response.ok) { throw errorFromResponse(response.status, payload); }`, add:

```ts
    // Any 2xx from an authenticated endpoint proves a session: "/" may skip the landing next time.
    if (path !== "/health") markSignedIn();
```

- Add one line to the file's top comment: `- A 2xx marks the browser as signed in (lib/returning.ts) and a 401 clears the mark: "/" skips the landing for a returning visitor.`

- [ ] **Step 6: Move the list to `/plans`**

Create `web/app/plans/page.tsx` with the content of today's `web/app/page.tsx`, changing only the doc comment's first words from `"/":` to `"/plans":`. The metadata stays `I tuoi piani · ${BRAND_NAME}`, and the component is renamed `PlansPage`.

- [ ] **Step 7: The skip script and the public header**

Create `web/components/landing/skip-landing-script.tsx`:

```tsx
import { SKIP_LANDING_BOOTSTRAP } from "@/lib/returning";

/**
 * Sends a returning, signed-in visitor from "/" to the plans before the landing paints. It uses the
 * ThemeScript pattern: text/javascript on the server, text/plain on the client, so React never runs
 * it twice. Render it first in the landing's markup. Only a full load of "/" runs it; client-side
 * navigation never executes inline scripts.
 */
export function SkipLandingScript() {
  return (
    <script
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: SKIP_LANDING_BOOTSTRAP }}
    />
  );
}
```

Create `web/components/landing/public-header.tsx`:

```tsx
import { LinkButton } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

/**
 * The landing's header (DESIGN.md, Landing): the lockup home, "Come funziona" (a jump down the
 * page, hidden below 480 px where the page is one short scroll), the bare theme toggle, and
 * "Accedi" to the plans. The plans page sends a signed-out visitor to TripTracker's login and back.
 */
export function PublicHeader() {
  return (
    <header className="border-b border-rule">
      <div className="mx-auto flex min-h-16 max-w-landing items-center justify-between gap-2 px-4 lg:px-7">
        <Wordmark href={ROUTES.home} />
        <nav aria-label="Pagina" className="flex items-center gap-2">
          <a
            href="#come-funziona"
            className="inline-flex min-h-11 items-center rounded-full px-2.5 text-small text-ink-2 no-underline hover:text-ink max-[30rem]:hidden"
          >
            Come funziona
          </a>
          <ThemeToggle variant="bare" className="pointer-coarse:size-11" />
          <LinkButton href={ROUTES.plans} variant="secondary" className="pointer-coarse:min-h-11">
            Accedi
          </LinkButton>
        </nav>
      </div>
    </header>
  );
}
```

In `web/app/globals.css`, in `@theme`, after `--container-prose: 40rem;`, add:

```css
  --container-landing: 76rem; /* the landing's measure, narrower than the app's page */
```

- [ ] **Step 8: The landing shell at `/`**

Replace `web/app/page.tsx` with:

```tsx
import type { Metadata } from "next";

import { PublicHeader } from "@/components/landing/public-header";
import { SkipLandingScript } from "@/components/landing/skip-landing-script";
import { BRAND_NAME, BRAND_TAGLINE } from "@/lib/brand";

/** Absolute: the root layout's "%s · Atlas" template would put the name last. */
export const metadata: Metadata = { title: { absolute: `${BRAND_NAME} · ${BRAND_TAGLINE}` } };

/**
 * "/": the public landing (brand spec, section 2), prerendered with no client fetch. A returning,
 * signed-in visitor is sent to /plans before it paints (SkipLandingScript, first in the markup).
 */
export default function LandingPage() {
  return (
    <>
      <SkipLandingScript />
      <PublicHeader />
      <main />
    </>
  );
}
```

- [ ] **Step 9: Run the tests**

Run: `npx vitest run lib/returning.test.ts lib/api.test.ts components/landing/landing.test.tsx components/nav components/ui/invariants.test.ts`

Expected: PASS. `app-header.test.tsx` already reads `ROUTES.plans`.

Then run `npm test && npm run typecheck && npm run lint`.

Expected: PASS. If a test asserted `/` as the list's address, change only the assertion, to `ROUTES.plans`.

- [ ] **Step 10: Commit**

```bash
git add web/lib web/app/page.tsx web/app/plans/page.tsx web/components/landing web/app/globals.css
git commit -m "feat(web): plans move to /plans, / becomes the landing, returning visitors skip it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The hero, the legend and the line map

**Files:**
- Create: `web/components/landing/landing-hero.tsx`, `web/components/landing/line-map.tsx`
- Modify: `web/app/globals.css` (lede size, pen/stamp/rise motion), `web/app/page.tsx`, `web/components/landing/landing.test.tsx`

**Interfaces:**
- Consumes: `ROUTES`, `DEMO_READY` (Task 1); `BRAND_TAGLINE` and `BRAND_DESCRIPTION`; `AGENT_LABELS` and `AgentName`; `LinkButton`.
- Produces:
  - `LandingHero({ demoReady?: boolean })`
  - `LineMap()`
  - the CSS utilities `text-lede`, `ease-pen`, `animate-pen`, `animate-ring`, `animate-stamp`, `animate-rise`, `animate-reveal`

- [ ] **Step 1: Write the failing tests**

Append to `web/components/landing/landing.test.tsx`. Add these imports:

```tsx
import { LandingHero } from "./landing-hero";
import { BRAND_DESCRIPTION, BRAND_TAGLINE } from "@/lib/brand";
import { AGENT_LABELS, AGENTS } from "@/lib/plan-events/labels";
```

Then the tests:

```tsx
describe("the hero", () => {
  it("greets with the tagline and the lede", () => {
    render(<LandingHero />);
    expect(screen.getByRole("heading", { level: 1, name: BRAND_TAGLINE })).toBeTruthy();
    expect(screen.getByText(BRAND_DESCRIPTION)).toBeTruthy();
  });

  it("until the demo exists, points to how it works and never to /demo", () => {
    const { container } = render(<LandingHero demoReady={false} />);
    expect(screen.getByRole("link", { name: "Scopri come funziona" }).getAttribute("href")).toBe("#come-funziona");
    expect(container.querySelector(`a[href="${ROUTES.demo}"]`)).toBeNull();
  });

  it("with the demo, its one action is the demo, and no Accedi", () => {
    render(<LandingHero demoReady />);
    expect(screen.getByRole("link", { name: "Guarda una corsa" }).getAttribute("href")).toBe(ROUTES.demo);
    expect(screen.queryByRole("link", { name: "Accedi" })).toBeNull();
  });

  it("names the five agents in the run's order, each with its job", () => {
    render(<LandingHero />);
    const legend = screen.getByRole("list", { name: "Legenda" });
    expect(within(legend).getAllByRole("listitem").map((item) => item.textContent)).toEqual(
      AGENTS.map((agent) => expect.stringContaining(AGENT_LABELS[agent])),
    );
  });

  it("draws the line map as one image with a description", () => {
    render(<LandingHero />);
    expect(screen.getAllByRole("img", { name: "Le cinque linee degli agenti convergono su Lisbona" }).length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

Run: `npx vitest run components/landing/landing.test.tsx`
Expected: FAIL: `./landing-hero` cannot be resolved.

- [ ] **Step 3: Motion and the lede size**

In `web/app/globals.css`, in `@theme`:

After `--text-input--line-height: 1.35;`, add:

```css
  --text-lede: 1.03125rem; /* 16.5px: the landing's lede and closing paragraph */
  --text-lede--line-height: 1.5;
```

After `--ease-expo: cubic-bezier(0.16, 1, 0.3, 1);`, add:

```css
  --ease-pen: cubic-bezier(0.65, 0, 0.35, 1); /* drawing a line: slow in, slow out */
```

After `--animate-toast-in: …;`, add:

```css
  /* The landing hero's one authored moment (DESIGN.md, Landing). Each is used only behind
     motion-safe:, so reduced motion shows the final state, still. */
  --animate-pen: pen 2s var(--ease-pen) both;
  --animate-ring: pen 1.2s var(--ease-pen) both;
  --animate-stamp: stamp 350ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
  --animate-rise: rise 500ms var(--ease-expo) both;
  --animate-reveal: arrive 500ms ease both;
```

Next to the other keyframes, add:

```css
  /* A line drawn as with a pen: from hidden (its dash offset = its dash length) to whole. */
  @keyframes pen {
    from {
      stroke-dashoffset: var(--pen, 720px);
    }
  }
  /* A station stamped onto the map: it lands slightly large and settles. */
  @keyframes stamp {
    from {
      opacity: 0;
      transform: scale(1.35);
    }
  }
  @keyframes rise {
    from {
      opacity: 0;
      transform: translateY(10px);
    }
  }
```

- [ ] **Step 4: The line map**

Create `web/components/landing/line-map.tsx`. It carries the mockup's two drawings:
- horizontal, 560 × 420, from 768 px;
- vertical, 360 × 480, below 768 px.

Use these class strings:

```tsx
import type { CSSProperties } from "react";

import { cx } from "@/components/ui/cx";

const LABEL = "Le cinque linee degli agenti convergono su Lisbona";
/** A line that draws in. Dash 720 is longer than any path here, so with no animation the line is
 * whole. */
const LINE = "fill-none [stroke-dasharray:720] motion-safe:animate-pen";
const STATION = "fill-ground [transform-box:fill-box] origin-center motion-safe:animate-stamp";
const TEXT = "fill-ink-2 font-sans text-[12px] font-medium motion-safe:animate-reveal";
const STRONG = "fill-ink font-sans text-[12px] font-semibold motion-safe:animate-reveal";
const at = (delay: number): CSSProperties => ({ animationDelay: `${delay}s` });
```

Port the mockup's elements one to one:
- **Paths** with `className={cx(LINE, "stroke-line-flights")}`, `strokeWidth={6}`, `strokeLinecap="round"`, `strokeLinejoin="round"` and `style={at(…)}`. The coordinator's path is 8 wide.
- **Stations** with `className={cx(STATION, "stroke-line-…")}` and `strokeWidth={3}`.
- **Wave lozenges** with `className={cx(STATION, "stroke-ink")}`.
- **Labels** with `TEXT` / `STRONG`.
- **The plate** in a `<g className="motion-safe:animate-rise" style={at(1.6)}>`. Its rect has `className="fill-line-flights"`; its text has `className="fill-on-line font-sans text-[12.5px] font-semibold"`.
- **The ring**: `<circle className="fill-none stroke-ink [stroke-dasharray:190] [--pen:190px] motion-safe:animate-ring" strokeWidth={1.5} style={at(2.4)} />`.
- **The destination**: a `<g className="[transform-box:fill-box] origin-center motion-safe:animate-stamp" style={at(2.1)}>` with the two circles (`fill-ground stroke-ink` 5 wide; `fill-ink` r 6) and the labels "Lisbona" (`font-cond text-[22px] font-semibold`), "14–18 aprile" and "piano pronto".

Each `<svg>` gets `role="img"`, `aria-label={LABEL}` and `className="h-auto w-full overflow-visible"`.
- The horizontal one: `hidden md:block`.
- The vertical one: `mx-auto block max-w-[26rem] md:hidden`.

The component returns both SVGs in a fragment.

- [ ] **Step 5: The hero**

Create `web/components/landing/landing-hero.tsx`:

```tsx
import { LinkButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { BRAND_DESCRIPTION, BRAND_TAGLINE } from "@/lib/brand";
import { AGENT_LABELS, AGENTS } from "@/lib/plan-events/labels";
import type { AgentName } from "@/lib/schemas/generated/ui-event";
import { DEMO_READY, ROUTES } from "@/lib/routes";

import { LineMap } from "./line-map";

/** What each agent does, in the legend (Italian, sentence case). */
const JOBS: Record<AgentName, string> = {
  coordinator: "decide e assembla il piano",
  flights: "cerca e confronta i voli",
  lodging: "trova dove dormire",
  activities: "sceglie cosa fare, con i biglietti",
  transport: "organizza come muoversi sul posto",
};

/**
 * The landing's first screen (DESIGN.md, Landing): the tagline, the lede, one call to action (the
 * demo once it exists, else a jump to "Come funziona"; "Accedi" lives in the header and the
 * closing), the legend of the five lines, and the line map converging on the sample destination.
 * On the phone the map comes before the legend; from 1080 px the legend sits under the copy.
 */
export function LandingHero({ demoReady = DEMO_READY }: { demoReady?: boolean }) {
  return (
    <section aria-labelledby="landing-title" className="mx-auto max-w-landing px-4 pt-8 lg:px-7 lg:pt-12">
      <div className="grid gap-7 lg:grid-cols-[0.95fr_1.15fr] lg:gap-x-8 lg:gap-y-8">
        <div className="lg:col-start-1 lg:row-start-1">
          <h1 id="landing-title" className="font-hero text-hero font-bold tracking-[-0.01em] lg:text-hero-lg">
            {BRAND_TAGLINE}
          </h1>
          <p className="mt-4 max-w-[30em] text-lede text-ink-2">{BRAND_DESCRIPTION}</p>
          <div className="mt-6 flex flex-wrap gap-2.5">
            {demoReady ? (
              <LinkButton href={ROUTES.demo} variant="primary" icon="play" className="pointer-coarse:min-h-11">
                Guarda una corsa
              </LinkButton>
            ) : (
              <LinkButton href="#come-funziona" variant="primary" className="pointer-coarse:min-h-11">
                Scopri come funziona
              </LinkButton>
            )}
          </div>
        </div>
        <div className="lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:self-start">
          <LineMap />
        </div>
        <div className="lg:col-start-1 lg:row-start-2">
          <p id="legenda" className="border-t border-rule pt-3 text-micro text-ink-2">
            Legenda
          </p>
          <ul aria-labelledby="legenda" className="mt-2 grid max-w-[30em] gap-y-2 text-meta">
            {AGENTS.map((agent) => (
              <li key={agent} data-agent={agent} className="grid grid-cols-[30px_7rem_minmax(0,1fr)] items-start gap-x-3.5">
                <span
                  aria-hidden="true"
                  className={cx("mt-[7px] block rounded-[3px] bg-line", agent === "coordinator" ? "h-2" : "h-1.5")}
                />
                <span className="font-semibold text-ink">{AGENT_LABELS[agent]}</span>
                <span className="text-ink-2">{JOBS[agent]}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <p className="mt-5 flex flex-wrap justify-between gap-x-4 gap-y-1 border-t border-rule pt-3 pb-4 text-micro text-ink-2">
        <span>Corsa di prova: Milano → Lisbona, 2 adulti e 2 bambini</span>
        <span>38°43′ N, 9°08′ O</span>
      </p>
    </section>
  );
}
```

The middle-dot rule applies here: the legend uses its own columns, and the map margin uses a colon and commas instead of separators.

In `web/app/page.tsx`, import `LandingHero` and replace `<main />` with:

```tsx
      <main>
        <LandingHero />
      </main>
```

- [ ] **Step 6: Run the tests**

Run: `npx vitest run components/landing`
Expected: PASS.

- [ ] **Step 7: Look at it**

Start `web-dev` (and `backend-demo` for the plans), then open `http://localhost:3000/`:
- **393 px:** the copy, then the vertical map converging at the bottom, then the legend.
- **1280 px:** the copy and legend on the left, the horizontal map on the right.
- **Both themes:** check each one.
- **Reduced motion:** emulate it once (javascript `matchMedia` can't change it; use the browser pane's emulation if available, otherwise check that the classes are `motion-safe:`). The map must appear whole.

- [ ] **Step 8: Commit**

```bash
git add web/components/landing web/app/page.tsx web/app/globals.css
git commit -m "feat(web): the landing hero, its legend and the line map

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: "Come funziona" with three real component samples

**Files:**
- Create: `web/components/landing/how-it-works.tsx`
- Modify: `web/app/page.tsx`, `web/components/landing/landing.test.tsx`

**Interfaces:**
- Consumes:
  - `RouteLine`, `TripFact` (`components/request/trip-outline`)
  - `Timeline`, `TimelineItem`, `TimelineTitle`, `TimelineMeta`, `TimelineNext`, `ToolChip`, `StatusBadge`, `AgentRoundel` (`components/ui`)
  - `DatePair`, `Chip`, `buttonClasses`, `Icon`, `VisuallyHidden`
- Produces: `HowItWorks()`.

- [ ] **Step 1: Write the failing tests**

Append to `landing.test.tsx` (add `import { HowItWorks } from "./how-it-works";`):

```tsx
describe("how it works", () => {
  it("is three stations on one line, reachable from the header", () => {
    const { container } = render(<HowItWorks />);
    expect(container.querySelector("section#come-funziona")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Descrivi il viaggio",
      "Guarda gli agenti",
      "Prenota entro la data",
    ]);
  });

  it("gives each sample one sentence for screen readers and keeps the drawing out of the way", () => {
    const { container } = render(<HowItWorks />);
    const figures = [...container.querySelectorAll("figure")];
    expect(figures).toHaveLength(3);
    for (const figure of figures) {
      expect(figure.querySelector("figcaption")?.textContent?.length).toBeGreaterThan(40);
      const drawing = figure.querySelector("[aria-hidden='true'][inert]");
      expect(drawing).toBeTruthy();
      expect(drawing?.querySelector("a, button, input")).toBeNull();
    }
  });

  it("shows a booking's two dates, the due one in amber words, and a button that is not a link", () => {
    const { container } = render(<HowItWorks />);
    const booking = container.querySelectorAll("figure")[2]!;
    expect(booking.textContent).toContain("Prenota entro");
    expect(booking.textContent).toContain("Quando");
    expect(booking.textContent).toContain("In scadenza");
    expect(booking.textContent).toContain("Prenota su Expedia");
    expect(booking.querySelector("a")).toBeNull();
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

Run: `npx vitest run components/landing/landing.test.tsx`
Expected: FAIL: `./how-it-works` cannot be resolved.

- [ ] **Step 3: Write the section**

Create `web/components/landing/how-it-works.tsx`:

```tsx
import type { ReactNode } from "react";

import { RouteLine, TripFact } from "@/components/request/trip-outline";
import { AgentRoundel } from "@/components/ui/agent";
import { buttonClasses } from "@/components/ui/button";
import { Chip, ToolChip } from "@/components/ui/chip";
import { cx } from "@/components/ui/cx";
import { DatePair } from "@/components/ui/date-pair";
import { Icon } from "@/components/ui/icon";
import { StatusBadge } from "@/components/ui/status-badge";
import { Timeline, TimelineItem, TimelineMeta, TimelineNext, TimelineTitle } from "@/components/ui/timeline";
import { VisuallyHidden } from "@/components/ui/visually-hidden";
import { AGENT_LABELS } from "@/lib/plan-events/labels";

/** The samples' fixed "now": the booking's deadline is two days away, so DatePair draws it due
 * soon (the amber's one job). The page is prerendered, so the sample never moves. */
const SAMPLE_NOW = Date.parse("2026-10-17T10:00:00+02:00");

/**
 * "Come funziona" (DESIGN.md, Landing): three stations on one ink line, vertical on the phone,
 * horizontal from 1080 px. Each one holds a real component with sample data. The samples are
 * illustrations: a screen reader hears one sentence (the figcaption), and the drawing is inert and
 * hidden from it, so nothing looks clickable that is not. The booking's "Prenota su Expedia" is
 * never a link (CLAUDE.md contract rule 4: booking URLs are never hand-written).
 */
export function HowItWorks() {
  return (
    <section
      id="come-funziona"
      aria-labelledby="come-funziona-titolo"
      className="mx-auto max-w-landing scroll-mt-4 px-4 pt-18 lg:px-7"
    >
      <h2 id="come-funziona-titolo" className="font-cond text-display font-semibold lg:text-display-lg">
        Come funziona
      </h2>
      <p className="mt-2 max-w-[36em] text-small text-ink-2">Tre fermate, dalla richiesta alla prenotazione.</p>
      <ol
        className={cx(
          "relative mt-9 grid gap-9 pl-9 lg:grid-cols-3 lg:gap-7 lg:pt-9 lg:pl-0",
          "before:absolute before:top-2.5 before:bottom-2.5 before:left-[11px] before:w-[3px] before:rounded-full before:bg-ink",
          "lg:before:inset-x-2 lg:before:top-1.5 lg:before:bottom-auto lg:before:h-[3px] lg:before:w-auto",
        )}
      >
        <Stop
          title="Descrivi il viaggio"
          text="Da dove parti e dove vuoi andare, oppure solo un'idea. Le date, chi viaggia, il budget. Bastano poche righe."
          caption="Esempio di richiesta: da Milano a Lisbona, dal 14 al 18 aprile 2027, 4 notti, 2 adulti e 2 bambini di 8 e 11 anni, 2.400 euro in tutto."
        >
          <RouteLine origin={{ text: "Milano" }} destination={{ text: "Lisbona" }} />
          <ul className="mt-3.5 grid gap-2 border-t border-rule pt-3 text-small">
            <TripFact icon="calendar-blank">14–18 aprile 2027, 4 notti</TripFact>
            <TripFact icon="users">2 adulti, 2 bambini di 8 e 11 anni</TripFact>
            <TripFact icon="wallet">2.400 € in tutto</TripFact>
          </ul>
        </Stop>
        <Stop
          title="Guarda gli agenti"
          text="Cinque agenti cercano in parallelo e vedi ogni passo mentre succede: chi lavora, su cosa, quanto costa."
          caption="Esempio di corsia: l'agente dei voli al lavoro. Ha ricevuto l'incarico, ha cercato su Expedia e ora sta cercando su Google Flights un volo diretto TAP, da 14 secondi."
        >
          <div className="flex items-center gap-2.5">
            <AgentRoundel agent="flights" size="md" />
            <span className="font-cond text-title font-semibold">{AGENT_LABELS.flights}</span>
            <StatusBadge state="working" agent="flights" className="ml-auto" />
          </div>
          <Timeline agent="flights" label="Esempio: la linea dei voli" className="mt-3">
            <TimelineItem kind="status" time="0:02">
              <TimelineTitle>Incarico ricevuto</TimelineTitle>
            </TimelineItem>
            <TimelineItem kind="tool" time="0:05">
              <TimelineTitle>Expedia · voli MXP→LIS · 14–18 apr</TimelineTitle>
              <TimelineMeta>1,3 s</TimelineMeta>
            </TimelineItem>
            <TimelineItem kind="current" time="0:06">
              <ToolChip agent="flights" title="Google Flights · TAP diretto" elapsed="0:14" />
            </TimelineItem>
            <TimelineNext />
          </Timeline>
        </Stop>
        <Stop
          title="Prenota entro la data"
          text="Ogni prenotazione ha due date: entro quando prenotarla e quando succede. Il prezzo ha la sua fonte, il link porta al sito giusto."
          caption="Esempio di prenotazione: il volo TAP tra Milano Malpensa e Lisbona, da prenotare entro lunedì 19 ottobre alle 23:59, in scadenza tra 2 giorni; il volo parte mercoledì 14 aprile alle 9:40. 472 euro, prezzo verificato su expedia.it."
        >
          <p className="text-body font-semibold">Volo TAP Milano Malpensa ⇄ Lisbona</p>
          <DatePair
            deadline={{ kind: "date", at: "2026-10-19T23:59:00+02:00" }}
            scheduledFor="2027-04-14T09:40:00+02:00"
            timeZone="Europe/Lisbon"
            deadlineTimeZone="Europe/Rome"
            startsAtHome
            tripLabel="a Lisbona"
            now={SAMPLE_NOW}
            className="mt-2.5"
          />
          <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-small text-ink-2">
            <span className="font-semibold text-ink">472,00 €</span>
            <Chip>verificato</Chip>
            <span>Fonte expedia.it, letto il 17 ott 2026, 10:12</span>
          </p>
          <span className={cx(buttonClasses("primary"), "mt-3.5")}>
            Prenota su Expedia
            <Icon name="arrow-square-out" size={16} />
          </span>
        </Stop>
      </ol>
    </section>
  );
}

/** One station: its ring on the line, its title and sentence, and the sample as a figure. */
function Stop({ title, text, caption, children }: { title: string; text: string; caption: string; children: ReactNode }) {
  return (
    <li className="relative">
      <span
        aria-hidden="true"
        className="absolute top-[3px] -left-9 size-4 translate-x-1 rounded-full border-[3.5px] border-ink bg-ground lg:-top-9 lg:left-0 lg:translate-x-0"
      />
      <h3 className="font-cond text-heading font-semibold">{title}</h3>
      <p className="mt-1.5 max-w-[32em] text-small text-ink-2">{text}</p>
      <figure className="m-0 mt-4.5">
        <figcaption>
          <VisuallyHidden>{caption}</VisuallyHidden>
        </figcaption>
        <div aria-hidden="true" inert className="rounded-md border border-rule bg-surface px-4 py-3.5">
          {children}
        </div>
      </figure>
    </li>
  );
}
```

Before running, check how `VisuallyHidden` renders inside `<figcaption>`: it must leave the caption's `textContent` readable. If `StatusBadge` or `AgentRoundel` need other props, read their files and adapt the call; keep the spirit.

In `web/app/page.tsx`, import `HowItWorks` and render it after `<LandingHero />`.

- [ ] **Step 4: Run the tests**

Run: `npx vitest run components/landing`
Expected: PASS.

- [ ] **Step 5: Look at it**

At 393 px and 1280 px, in dark and light:
- the vertical line becomes horizontal from 1080 px;
- the amber appears on the due "Prenota entro" and nowhere else;
- the samples aren't clickable;
- the "Come funziona" link in the header jumps to the section, and its title doesn't end up under the top edge.

- [ ] **Step 6: Commit**

```bash
git add web/components/landing web/app/page.tsx
git commit -m "feat(web): Come funziona, three stations with real component samples

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The closing section and the footer

**Files:**
- Create: `web/components/landing/landing-close.tsx`, `web/components/landing/converging-lines.tsx`, `web/components/landing/landing-footer.tsx`
- Modify: `web/app/page.tsx`, `web/components/landing/landing.test.tsx`

**Interfaces:**
- Consumes: `ROUTES`, `DEMO_READY`, `LinkButton`, `Wordmark`.
- Produces: `LandingClose({ demoReady?: boolean })`, `ConvergingLines({ className })`, `LandingFooter()`.

- [ ] **Step 1: Write the failing tests**

Append to `landing.test.tsx` (add imports for `LandingClose`):

```tsx
describe("the closing", () => {
  it("until the demo exists, says Atlas is by invitation and offers to sign in", () => {
    const { container } = render(<LandingClose demoReady={false} />);
    expect(screen.getByRole("heading", { level: 2, name: "Atlas è su invito." })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Accedi" }).getAttribute("href")).toBe(ROUTES.plans);
    expect(container.querySelector(`a[href="${ROUTES.demo}"]`)).toBeNull();
  });

  it("with the demo, offers it first, then sign in, and says access is by invitation", () => {
    render(<LandingClose demoReady />);
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([ROUTES.demo, ROUTES.plans]);
    expect(screen.getByText("Accesso su invito.")).toBeTruthy();
  });

  it("puts no demo link anywhere on today's landing", () => {
    const { container } = render(<LandingPage />);
    expect(container.querySelector(`a[href="${ROUTES.demo}"]`)).toBeNull();
    expect(screen.getByRole("contentinfo")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run them and watch them fail**

Run: `npx vitest run components/landing/landing.test.tsx`
Expected: FAIL: `./landing-close` cannot be resolved.

- [ ] **Step 3: Write the closing, the lines and the footer**

`converging-lines.tsx`: the Open Graph image's five lines (viewBox `0 0 1056 150`, the same paths as `app/opengraph-image.tsx`'s `CONVERGING_LINES`), in token classes:
- `stroke-line-coordinator` (9 wide);
- `stroke-line-flights`, `stroke-line-lodging`, `stroke-line-activities`, `stroke-line-transport` (7 wide);
- round caps and joins;
- the ring `fill-ground stroke-ink` (r 26, 7 wide) and the dot `fill-ink` (r 9).

The SVG has `aria-hidden="true"` and `className={cx("block h-auto w-full", className)}`.

`landing-close.tsx`:

```tsx
import { LinkButton } from "@/components/ui/button";
import { DEMO_READY, ROUTES } from "@/lib/routes";

import { ConvergingLines } from "./converging-lines";

/**
 * The landing's closing (DESIGN.md, Landing): the five lines entering the destination, then the
 * invitation. With the demo: watch a whole run, then sign in, "Accesso su invito.". Until it
 * exists: Atlas is by invitation, sign in. "Accedi" lives here and in the header, never in the hero.
 */
export function LandingClose({ demoReady = DEMO_READY }: { demoReady?: boolean }) {
  return (
    <section aria-labelledby="landing-close-title" className="mx-auto max-w-landing px-4 pt-20 pb-14 lg:px-7">
      <ConvergingLines className="mb-7" />
      {demoReady ? (
        <>
          <h2 id="landing-close-title" className="font-cond text-display font-semibold lg:text-display-lg">
            Guarda una corsa intera, senza account.
          </h2>
          <p className="mt-2.5 max-w-[34em] text-lede text-ink-2">
            Una corsa registrata, riprodotta con i veri componenti di Atlas: gli agenti al lavoro, il costo che
            sale, il piano finito con le sue prenotazioni. Dura meno di un minuto e non costa nulla.
          </p>
          <div className="mt-5.5 flex flex-wrap gap-2.5">
            <LinkButton href={ROUTES.demo} variant="primary" icon="play" className="pointer-coarse:min-h-11">
              Guarda una corsa
            </LinkButton>
            <LinkButton href={ROUTES.plans} variant="secondary" className="pointer-coarse:min-h-11">
              Accedi
            </LinkButton>
          </div>
          <p className="mt-3.5 text-meta text-ink-2">Accesso su invito.</p>
        </>
      ) : (
        <>
          <h2 id="landing-close-title" className="font-cond text-display font-semibold lg:text-display-lg">
            Atlas è su invito.
          </h2>
          <p className="mt-2.5 max-w-[34em] text-lede text-ink-2">
            Se hai un invito, accedi con il tuo account TripTracker e pianifica il prossimo viaggio. Presto qui
            potrai guardare una corsa intera, senza account.
          </p>
          <div className="mt-5.5">
            <LinkButton href={ROUTES.plans} variant="primary" icon="sign-in" className="pointer-coarse:min-h-11">
              Accedi
            </LinkButton>
          </div>
        </>
      )}
    </section>
  );
}
```

`landing-footer.tsx`:

```tsx
import { Wordmark } from "@/components/ui/wordmark";
import { ROUTES } from "@/lib/routes";

/** The landing's footer: the lockup home and the one honest line about prices. */
export function LandingFooter() {
  return (
    <footer className="border-t border-rule">
      <div className="mx-auto flex max-w-landing flex-wrap items-center justify-between gap-x-6 gap-y-2.5 px-4 pt-5 pb-7 text-meta text-ink-2 lg:px-7">
        <Wordmark href={ROUTES.home} />
        <p>Prezzi e disponibilità si confermano sempre sul sito del fornitore.</p>
      </div>
    </footer>
  );
}
```

In `web/app/page.tsx`, render `<LandingClose />` after `<HowItWorks />` inside `<main>`, and `<LandingFooter />` after `</main>`.

- [ ] **Step 4: Run the tests**

Run: `npx vitest run components/landing && npm test && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/landing web/app/page.tsx
git commit -m "feat(web): the landing's closing and footer

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Docs

**Files:**
- Modify: `web/DESIGN.md`, `web/PRODUCT.md`, `CLAUDE.md`, `web/README.md`

- [ ] **Step 1: DESIGN.md**

- **"Where things live":** add the rows below.
  - Landing: `web/app/page.tsx` and `web/components/landing/`.
  - Returning visitors: `web/lib/returning.ts`.
  - `ROUTES` / `DEMO_READY`: `web/lib/routes.ts`.
- **"Typography" → Hierarchy:** add the Lede row: `text-lede`, Barlow 400, 16.5 / 1.5, the landing's lede and closing paragraph.
- **New `## Landing` section,** before `## Map`. It describes:
  - the route (`/`, prerendered, public) and the skip for returning visitors (mark, referrer rule, fail-safe);
  - the public header;
  - the hero, with Michele's decisions 1 and 2;
  - the legend and the two line maps (horizontal from 768 px, vertical below);
  - "Come funziona": samples are figures, with a caption for screen readers and an inert drawing, and the booking button is never a link;
  - the closing in both `DEMO_READY` states;
  - the footer;
  - the motion: the hero map is the landing's one authored moment (pen, stamp, rise, ring; `--ease-pen`; `motion-safe:` only), a named exception to "Report, Don't Perform" for the landing and the demo, as the spec's section 4 rule allows.
- **"Motion" table:** add the row "The landing map draws in (once per load)": lines are drawn with `--ease-pen`, 2 s, staggered; stations stamp at 350 ms; the plate rises; the ring draws in 1.2 s. Reduced motion shows the final state, still.

- [ ] **Step 2: PRODUCT.md**

In "Operating Context", replace the "**Three screens**" bullet's routes:
- `/` is the public landing;
- `/plans` is the recent plans;
- `/new` and `/plans/[id]` stay as they are.

Under "Decisions" → "2026-10-14: the brand restyle", add: "**2026-10-17**: the landing approved from a mockup, with 'Accedi' only in the header and the closing, the map before the legend on the phone, and one choreographed moment."

- [ ] **Step 3: CLAUDE.md and web/README.md**

Every line that lists the routes as `/ (plans)` becomes `/ (landing, public), /plans (plans)`. Find them with `grep -n "/ (plans)" CLAUDE.md web/README.md`.

- [ ] **Step 4: Run the tests and commit**

Run: `cd web && npm test`
Expected: PASS. The token test still agrees with the frontmatter.

```bash
git add web/DESIGN.md web/PRODUCT.md CLAUDE.md web/README.md
git commit -m "docs(web): the landing, /plans and returning visitors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Verification, critique, review

- [ ] **Step 1: Every web check CI runs**

Run from `web/`:

```bash
npm run gen:schemas -- --check && npm run lint && npm run typecheck && npm test && npm run build
```

Expected: everything exits 0. In the route table, `/` and `/plans` are static (○ or ◐). Restart `web-dev` afterwards: a build into `.next` can leave the dev server serving stale CSS.

- [ ] **Step 2: The JS budget**

```bash
NEXT_DIST_DIR=.next-build npm run build && NEXT_DIST_DIR=.next-build npm run measure:js
git checkout -- tsconfig.json
```

Expected:
- `/plans/[id]` ≤ 192.2 KB;
- `/` below `/plans`.

Record the figures in `web/README.md` ("JS budget").

- [ ] **Step 3: The browser**

**The skip:**
1. Clear `atlas-signed-in` and open `/`: the landing shows.
2. Set `localStorage.setItem("atlas-signed-in","1")` and reload `/` with a full load: you land on `/plans`.
3. From `/plans`, click a link to `/` if any. Otherwise check that same-origin arrival keeps the landing, using `history` plus `location.assign` from a page of the site.
4. Clear the mark at the end.

**Every landing section** at 393 px and 1280 px, in dark and light. Also check:
- `/plans` and a plan page;
- the 404's "Torna ai piani".

- [ ] **Step 4: The design gate**

Run one impeccable critique round on `/`: dual-agent (A, the design review, unanchored; B, the detector plus the browser). Fix P0 and P1. Save the record as `web/.impeccable/critique/front-door.md`.

- [ ] **Step 5: The whole-branch review**

Use a fresh reviewer (opus) with this plan, the spec and this plan's Review Focus. Fix Critical and Important; record Minor as deferred.

- [ ] **Step 6: The PR**

Push `feat/atlas-front-door` and open a PR against `main`. The body covers:
- what changed;
- the `DEMO_READY` gate;
- Michele's three decisions;
- the critique score;
- the JS figures;
- the deferred minors.
