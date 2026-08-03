import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { LoginPage } from "../pages/LoginPage";
import { api } from "../lib/api";

describe("LoginPage", () => {
  it("renders a password-only administrator login without embedding a token", () => {
    const markup = renderToStaticMarkup(<LoginPage onAuthenticated={vi.fn()} />);

    expect(markup).toContain('type="password"');
    expect(markup).toContain("管理员登录");
    expect(markup).not.toContain("X-ADX-Operator-Token");
    expect(markup).not.toContain("test-operator-token");
  });

  it("includes the signed session cookie for a separately hosted local API", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ authenticated: true }) })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ items: [] }) });
    vi.stubGlobal("fetch", fetchMock);

    await api.loginOperator("admin-password");
    await api.listAccounts();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: "include", method: "POST" });
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ credentials: "include" });
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain("X-ADX-Operator-Token");
    vi.unstubAllGlobals();
  });
});
