import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LiveHeader } from "./live-header";

afterEach(cleanup);

describe("LiveHeader", () => {
  it("holds a bar of its own (the demo's) inside the plan's state group, on its own row", () => {
    render(
      <LiveHeader
        title="Lisbona"
        summary={null}
        status="running"
        interrupting={false}
        elapsed="0:12"
        costCents={null}
        budgetCents={60}
        bar={<p>Barra della demo</p>}
      />,
    );
    const group = screen.getByRole("group", { name: "Stato del piano" });
    expect(group.textContent).toContain("Barra della demo");
    expect(screen.getByText("Barra della demo").parentElement?.className).toContain("[grid-area:bar]");
  });

  it("names a finished plan's cost as it is told (the demo's recorded run)", () => {
    render(
      <LiveHeader
        title="Lisbona"
        summary={null}
        status="ready"
        interrupting={false}
        elapsed="0:45"
        costCents={41}
        budgetCents={60}
        costLabel="Costo della corsa registrata"
      />,
    );
    expect(screen.getByRole("group", { name: "Stato del piano" }).textContent).toContain(
      "Costo della corsa registrata 0,41 $",
    );
  });

  it("keeps the theme toggle bare in the control bar, as in the header, so it is never a twin of a ringed button", () => {
    render(
      <LiveHeader
        title="Lisbona, 14–18 apr"
        summary={null}
        status="running"
        interrupting={false}
        elapsed="0:12"
        costCents={null}
        budgetCents={100}
      />,
    );
    const toggle = screen.getByRole("button", { name: "Passa al tema chiaro" });
    expect(toggle.className).not.toMatch(/\bborder-rule-strong\b/);
    expect(toggle.className).toMatch(/\bborder-transparent\b/);
  });
});
