import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { NIGHT } from "@/lib/brand-mark";

import { Mark } from "./mark";
import { Wordmark } from "./wordmark";

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

afterEach(cleanup);

/** The `--name: #rrggbb;` tokens of the dark ("Carta notturna") block of globals.css. */
function nightTokens(): Record<string, string> {
  const css = readFileSync(path.join(webDir, "app/globals.css"), "utf8");
  const start = css.indexOf(':root,\n[data-theme="dark"] {');
  const block = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries([...block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6});/g)].map((m) => [m[1]!, m[2]!]));
}

describe("Mark", () => {
  it("is decorative and drawn only in theme tokens, so it follows the nearest data-theme", () => {
    const { container } = render(<Mark className="size-7" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("aria-hidden")).toBe("true");
    expect(svg.outerHTML).not.toMatch(/#[0-9a-f]{3,6}\b/i);
    expect([...svg.querySelectorAll("path, circle")].map((shape) => shape.getAttribute("class"))).toEqual([
      "fill-none stroke-line-flights",
      "fill-none stroke-line-lodging",
      "fill-none stroke-line-coordinator",
      "fill-ground stroke-ink",
    ]);
  });

  it("keeps the fixed night colours (icons, link preview) equal to the dark theme's tokens", () => {
    const tokens = nightTokens();
    expect(NIGHT).toEqual({
      ground: tokens.ground,
      ink: tokens.ink,
      coordinator: tokens["line-coordinator"],
      flights: tokens["line-flights"],
      lodging: tokens["line-lodging"],
      activities: tokens["line-activities"],
      transport: tokens["line-transport"],
    });
  });
});

describe("Wordmark", () => {
  it("is the mark and the name, and the link home is named by the name alone", () => {
    render(<Wordmark href="/somewhere" />);
    const link = screen.getByRole("link", { name: "Atlas" });
    expect(link.getAttribute("href")).toBe("/somewhere");
    expect(link.querySelector("svg[aria-hidden='true']")).toBeTruthy();
  });

  it("keeps the name for screen readers when compact hides it on narrow phones", () => {
    render(<Wordmark href="/somewhere" compact />);
    const name = screen.getByText("Atlas");
    expect(name.className).toContain("max-[25rem]:sr-only");
    expect(screen.getByRole("link", { name: "Atlas" })).toBeTruthy();
  });
});
