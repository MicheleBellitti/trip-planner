import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { LiveHeader } from "./live-header";

afterEach(cleanup);

describe("LiveHeader", () => {
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
