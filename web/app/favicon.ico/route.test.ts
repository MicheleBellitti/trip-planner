// @vitest-environment node
import { describe, expect, it } from "vitest";

import * as favicon from "./route";

describe("/favicon.ico", () => {
  it("answers with the mark as a PNG, not the 404 page", async () => {
    const response = await favicon.GET();
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("image/png");
    const bytes = new Uint8Array(await response.arrayBuffer());
    expect([...bytes.slice(0, 8)]).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  });

  it("reads nothing from the request, so the build prerenders it", () => {
    expect(favicon.GET.length).toBe(0);
  });
});
