import { describe, expect, it } from "vitest";

import { exampleRequestForm, validateRequestForm } from "@/lib/request-form";

import { describeExample, EXAMPLE_HREF, exampleRequest } from "./example";

describe("the home page's example", () => {
  it("says the spec's request, and the form it opens says the same", () => {
    const example = exampleRequest("2026-10-12");
    expect(example.sentence).toBe("Lisbona a metà aprile, 2 adulti e 2 bambini, 2.400 €");
    expect(example).toMatchObject({
      origin: "Milano",
      destination: "Lisbona",
      dates: "14–18 aprile 2027, 4 notti",
      travelers: "2 adulti, 2 bambini di 8 e 11 anni",
      budget: "2.400 €",
    });
    expect(validateRequestForm(exampleRequestForm("2026-10-12"), { today: "2026-10-12" }).ok).toBe(true);
    expect(EXAMPLE_HREF).toBe("/new?esempio=1");
  });

  it("follows the form's values", () => {
    const values = { ...exampleRequestForm("2026-10-12"), adults: 1, childAges: [] };
    expect(describeExample(values).sentence).toBe("Lisbona a metà aprile, 1 adulto, 2.400 €");
  });
});
