import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LandingPage from "@/app/page";
import { buttonClasses } from "@/components/ui/button";
import { BRAND_DESCRIPTION, BRAND_TAGLINE } from "@/lib/brand";
import { AGENT_LABELS, AGENTS } from "@/lib/plan-events/labels";
import { SKIP_LANDING_BOOTSTRAP } from "@/lib/skip-landing";
import { ROUTES } from "@/lib/routes";

import { HowItWorks } from "./how-it-works";
import { LandingClose } from "./landing-close";
import { LandingHero } from "./landing-hero";

vi.mock("@/components/ui/theme-toggle", () => ({ ThemeToggle: () => <button type="button">Tema</button> }));
vi.mock("@/app/actions/waitlist", () => ({ joinWaitlistAction: vi.fn() }));

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
    const items = within(legend).getAllByRole("listitem").map((item) => item.textContent ?? "");
    expect(items).toHaveLength(AGENTS.length);
    AGENTS.forEach((agent, index) => expect(items[index]).toContain(AGENT_LABELS[agent]));
  });

  it("draws the line map as one image with a description", () => {
    render(<LandingHero />);
    expect(screen.getAllByRole("img", { name: "Le cinque linee degli agenti convergono su Lisbona" }).length).toBeGreaterThan(0);
  });

  it("says plainly that the agents are AI", () => {
    render(<LandingHero />);
    expect(screen.getByText(BRAND_DESCRIPTION).textContent).toContain("agenti AI");
  });

  it("names every line at its head on both maps, so no line is a colour alone", () => {
    render(<LandingHero />);
    const maps = screen.getAllByRole("img", { name: "Le cinque linee degli agenti convergono su Lisbona" });
    expect(maps).toHaveLength(2);
    for (const map of maps) {
      const words = [...map.querySelectorAll("text")].map((text) => text.textContent);
      AGENTS.forEach((agent) => expect(words).toContain(AGENT_LABELS[agent]));
    }
  });

  it("shows the live plate only while the map draws: its finished state is the plan", () => {
    render(<LandingHero />);
    for (const map of screen.getAllByRole("img", { name: "Le cinque linee degli agenti convergono su Lisbona" })) {
      const plate = [...map.querySelectorAll("text")].find((text) => text.textContent?.includes("0:14"));
      expect(plate).toBeTruthy();
      expect(plate?.closest("g")?.getAttribute("class")).toContain("opacity-0");
    }
  });
});

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

  it("marks each sample visibly as an example, inside the drawing", () => {
    const { container } = render(<HowItWorks />);
    for (const figure of container.querySelectorAll("figure")) {
      const drawing = figure.querySelector("[inert]");
      expect([...(drawing?.querySelectorAll("*") ?? [])].some((el) => el.textContent === "Esempio")).toBe(true);
    }
  });

  it("draws the sample's booking button below the page's own actions", () => {
    render(<HowItWorks />);
    const sample = screen.getByText("Prenota su Expedia");
    expect(sample.className).toContain(buttonClasses("secondary"));
    expect(sample.className).not.toContain(buttonClasses("primary"));
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

describe("the closing", () => {
  it("until the demo exists, says Atlas is by invitation, offers the waitlist and then sign in", () => {
    const { container } = render(<LandingClose demoReady={false} />);
    expect(screen.getByRole("heading", { level: 2, name: "Atlas è su invito." })).toBeTruthy();
    const form = screen.getByLabelText("Indirizzo email").closest("form")!;
    expect(form.querySelector('input[name="source"]')?.getAttribute("value")).toBe("landing");
    expect(screen.getByRole("button", { name: "Mettimi in lista" })).toBeTruthy();
    const signIn = screen.getByRole("link", { name: "Accedi" });
    expect(signIn.getAttribute("href")).toBe(ROUTES.login); // the login forwards a live session to the plans
    expect(form.compareDocumentPosition(signIn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // the list first
    expect(container.querySelector(`a[href="${ROUTES.demo}"]`)).toBeNull();
  });

  it("with the demo, offers it first, then sign in, and the waitlist under 'Accesso su invito.'", () => {
    render(<LandingClose demoReady />);
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([ROUTES.demo, ROUTES.plans]);
    expect(screen.getByRole("heading", { level: 3, name: "Accesso su invito." })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Mettimi in lista" })).toBeTruthy();
  });

  it("puts no demo link anywhere on today's landing, and ends with a footer", () => {
    const { container } = render(<LandingPage />);
    expect(container.querySelector(`a[href="${ROUTES.demo}"]`)).toBeNull();
    expect(screen.getByRole("contentinfo")).toBeTruthy();
  });
});
