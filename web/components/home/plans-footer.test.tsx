import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PlansPage from "@/app/plans/page";

import { PlansFooter } from "./plans-footer";

vi.mock("@/components/home/plan-list", () => ({ PlanList: () => <div data-testid="list" /> }));
vi.mock("@/components/nav/app-header", () => ({ AppHeader: () => <header /> }));
// The footer's link is a full load, never a client navigation: rendered on the client, the landing
// would create its skip script there (React refuses and logs it). Any next/link use fails here.
vi.mock("next/link", () => ({
  default: () => {
    throw new Error("next/link");
  },
}));

afterEach(cleanup);

describe("the plans page's ending", () => {
  it("offers how Atlas works, on the landing, as a link that shows the landing even when signed in", () => {
    render(<PlansFooter />);
    expect(screen.getByRole("link", { name: "Come funziona Atlas" }).getAttribute("href")).toBe("/#come-funziona");
  });

  it("ends the page after the list, so the photo credit is not the last line", () => {
    const { container } = render(<PlansPage />);
    const last = container.lastElementChild;
    expect(last?.tagName).toBe("FOOTER");
    expect(last?.textContent).toContain("Come funziona Atlas");
  });
});
