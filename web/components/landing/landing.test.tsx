import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LandingPage from "@/app/page";
import { BRAND_DESCRIPTION, BRAND_TAGLINE } from "@/lib/brand";
import { AGENT_LABELS, AGENTS } from "@/lib/plan-events/labels";
import { SKIP_LANDING_BOOTSTRAP } from "@/lib/skip-landing";
import { ROUTES } from "@/lib/routes";

import { HowItWorks } from "./how-it-works";
import { LandingClose } from "./landing-close";
import { LandingHero } from "./landing-hero";

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

  it("puts no demo link anywhere on today's landing, and ends with a footer", () => {
    const { container } = render(<LandingPage />);
    expect(container.querySelector(`a[href="${ROUTES.demo}"]`)).toBeNull();
    expect(screen.getByRole("contentinfo")).toBeTruthy();
  });
});
