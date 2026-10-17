import { describe, expect, it } from "vitest";

import { invitationEmail } from "./invitation-email";

describe("the invitation email", () => {
  const email = invitationEmail({ loginUrl: "https://atlas.bellittim.com/login", email: "friend@example.com" });

  it("names the product, the invited address and the login page, in that order", () => {
    expect(email.subject).toBe("Hai un invito per Atlas");
    expect(email.text).toContain("usa questo indirizzo: friend@example.com");
    expect(email.text.split("\n")).toContain("https://atlas.bellittim.com/login");
    expect(email.text.indexOf("friend@example.com")).toBeLessThan(email.text.indexOf("https://"));
    expect(email.html).toContain('<a href="https://atlas.bellittim.com/login">Entra in Atlas</a>');
    expect(email.html).toContain("<strong>friend@example.com</strong>");
  });

  it("never puts the address in the link", () => {
    expect(email.text).not.toMatch(/login\?/);
    expect(email.html).not.toMatch(/login\?/);
  });

  it("escapes what it interpolates into the HTML", () => {
    const tricky = invitationEmail({ loginUrl: "https://atlas.bellittim.com/login?a=1&b=2", email: "a<b>@example.com" });
    expect(tricky.html).toContain("https://atlas.bellittim.com/login?a=1&amp;b=2");
    expect(tricky.html).toContain("a&lt;b&gt;@example.com");
    expect(tricky.html).not.toContain("a<b>@");
  });
});
