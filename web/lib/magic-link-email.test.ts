import { describe, expect, it } from "vitest";

import { magicLinkEmail } from "./magic-link-email";

describe("the sign-in email", () => {
  const url = "https://atlas.bellittim.com/api/auth/magic-link/verify?token=abc&callbackURL=%2Fplans%3Fx%3D1%26y%3D2";
  const email = magicLinkEmail({ url, expiresInMinutes: 5 });

  it("names the product and says how long the link lasts", () => {
    expect(email.subject).toBe("Il tuo link per entrare in Atlas");
    expect(email.text).toContain(url);
    expect(email.text).toContain("Vale cinque minuti e funziona una volta sola");
    expect(email.html).toContain("Vale cinque minuti");
  });

  it("escapes the URL in the HTML and keeps it verbatim in the text", () => {
    expect(email.html).toContain('href="https://atlas.bellittim.com/api/auth/magic-link/verify?token=abc&amp;callbackURL=');
    expect(email.html).not.toContain("&callbackURL");
    expect(email.text.split("\n")).toContain(url);
  });

  it("spells other durations in digits", () => {
    expect(magicLinkEmail({ url, expiresInMinutes: 7 }).text).toContain("Vale 7 minuti");
    expect(magicLinkEmail({ url, expiresInMinutes: 1 }).text).toContain("Vale un minuto");
  });
});
