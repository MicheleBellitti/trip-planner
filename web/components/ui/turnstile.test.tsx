import { act, cleanup, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_EVENT } from "./theme";
import { resetTurnstileScript, Turnstile, type TurnstileHandle } from "./turnstile";

const api = { render: vi.fn(() => "widget-1"), reset: vi.fn(), remove: vi.fn() };

beforeEach(() => {
  api.render.mockClear();
  api.reset.mockClear();
  api.remove.mockClear();
  resetTurnstileScript();
  delete process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;
  document.documentElement.removeAttribute("data-theme");
  for (const script of document.querySelectorAll("script[src*='challenges.cloudflare.com']")) script.remove();
  delete (window as { turnstile?: unknown }).turnstile;
});

afterEach(cleanup);

describe("Turnstile", () => {
  it("renders nothing and never calls back without a site key", () => {
    const onToken = vi.fn();
    render(<Turnstile onToken={onToken} />);
    expect(screen.queryByTestId("turnstile")).toBeNull();
    expect(document.querySelector("script[src*='challenges.cloudflare.com']")).toBeNull();
    expect(onToken).not.toHaveBeenCalled();
  });

  it("loads the script once, renders the widget in the page's theme, hands tokens over, resets and removes", async () => {
    process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY = "site-key";
    document.documentElement.setAttribute("data-theme", "light");
    const onToken = vi.fn();
    const ref = createRef<TurnstileHandle>();
    const { unmount } = render(<Turnstile ref={ref} onToken={onToken} action="waitlist" className="mt-2" />);
    const box = screen.getByTestId("turnstile");
    expect(box.className).toBe("mt-2");

    const script = document.querySelector<HTMLScriptElement>("script[src*='challenges.cloudflare.com']");
    expect(script?.src).toContain("render=explicit");
    expect(script?.async).toBe(true);
    (window as unknown as { turnstile: typeof api }).turnstile = api;
    await act(async () => {
      script?.onload?.(new Event("load"));
      await Promise.resolve();
    });

    expect(api.render).toHaveBeenCalledTimes(1);
    const [container, options] = api.render.mock.calls[0] as unknown as [HTMLElement, Record<string, unknown>];
    expect(container).toBe(box);
    expect(options).toMatchObject({ sitekey: "site-key", theme: "light", size: "flexible", action: "waitlist" });

    (options.callback as (token: string) => void)("tok-1");
    expect(onToken).toHaveBeenLastCalledWith("tok-1");
    (options["expired-callback"] as () => void)();
    expect(onToken).toHaveBeenLastCalledWith(null);

    act(() => ref.current?.reset());
    expect(api.reset).toHaveBeenCalledWith("widget-1");

    // The theme changed: the widget is drawn again in the new theme.
    document.documentElement.setAttribute("data-theme", "dark");
    await act(async () => {
      window.dispatchEvent(new Event(THEME_EVENT));
      await Promise.resolve();
    });
    expect(api.remove).toHaveBeenCalledWith("widget-1");
    expect(api.render).toHaveBeenCalledTimes(2);
    expect((api.render.mock.calls[1] as unknown as [HTMLElement, Record<string, unknown>])[1].theme).toBe("dark");

    unmount();
    expect(api.remove).toHaveBeenCalledTimes(2);
  });
});
