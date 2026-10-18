import { describe, expect, it } from "vitest";

import { clientIp } from "./request-ip";

describe("clientIp", () => {
  it("prefers x-real-ip, then the first forwarded address, else null", () => {
    expect(clientIp(new Headers({ "x-real-ip": "203.0.113.9", "x-forwarded-for": "1.1.1.1" }))).toBe("203.0.113.9");
    expect(clientIp(new Headers({ "x-forwarded-for": "198.51.100.2, 10.0.0.1" }))).toBe("198.51.100.2");
    expect(clientIp(new Headers({ "x-forwarded-for": " , " }))).toBeNull();
    expect(clientIp(new Headers())).toBeNull();
  });
});
