// @ts-expect-error The test runtime provides Node built-ins; the production TypeScript config intentionally omits Node types.
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ToastContext } from "../components/ui/useToast";
import { OAuthAppsSection } from "../features/oauth/OAuthAppsSection";
import type { OAuthAppRead } from "../types/api";


const baseApp: OAuthAppRead = {
  id: 1,
  account_id: 10,
  client_id: "public-client-id",
  redirect_uri: "https://example.com/oauth/google/callback",
  scopes: "https://www.googleapis.com/auth/admanager",
  app_status: "active",
  verification_status: "verified",
  authorization_status: "authorized",
  flow_status: "completed",
  runtime_status: "healthy",
  active_credential_version: 4,
  pending_credential_version: null,
  credential_fingerprint: "1234567890abcdef1234567890abcdef",
  failure_class: null,
  failure_count: 0,
  last_verified_at: "2026-07-31T08:00:00Z",
  revoked_at: null,
  publishing_status: "in_production",
  next_action: null,
  authorization_requested_at: null,
  authorization_completed_at: "2026-07-31T07:00:00Z",
  access_token_expires_at: null,
  refresh_token_updated_at: null,
  granted_scopes: "https://www.googleapis.com/auth/admanager",
  refresh_token_present: true,
  created_at: "2026-07-30T00:00:00Z",
  updated_at: "2026-07-31T08:00:00Z",
};


function renderApps(apps: OAuthAppRead[]): string {
  return renderToStaticMarkup(
    <ToastContext.Provider value={{ pushToast: vi.fn() }}>
      <OAuthAppsSection accounts={[]} oauthApps={apps} onChanged={vi.fn()} />
    </ToastContext.Provider>,
  );
}

function getTableParts(markup: string) {
  const table = markup.match(/<table[^>]*>([\s\S]*?)<\/table>/)?.[0] ?? "";
  const headers = [...table.matchAll(/<th[^>]*>([\s\S]*?)<\/th>/g)].map((match) => match[1]);
  const firstRow = table.match(/<tbody><tr[^>]*>([\s\S]*?)<\/tr>/)?.[1] ?? "";
  const cells = [...firstRow.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((match) => match[1]);
  return { table, headers, cells };
}


describe("OAuthAppsSection health state", () => {
  it("keeps the authorization action inside the Account / App cell in an eight-column table", () => {
    const { table, headers, cells } = getTableParts(renderApps([baseApp]));

    expect(table).toContain('class="data-table oauth-apps-table"');
    expect(headers).toHaveLength(8);
    expect(headers).not.toContain("Action");
    expect(cells).toHaveLength(8);
    expect(cells[1]).toContain("Reauthorize");
    expect(cells[7]).not.toContain("Reauthorize");
  });

  it("uses the eight-column empty state", () => {
    const markup = renderApps([]);

    expect(markup).toContain('colSpan="8"');
    expect(markup).not.toContain('colSpan="9"');
  });

  it("defines OAuth-only wrapping and horizontal overflow layout contracts", () => {
    const styles = readFileSync("src/styles.css", "utf8");

    expect(styles).toMatch(/\.oauth-apps-table\s*\{/);
    expect(styles).toMatch(/\.oauth-app-info\s*\{[^}]*overflow-wrap:\s*anywhere/s);
    expect(styles).toMatch(/\.oauth-apps-table-card\s*\{[^}]*overflow-x:\s*auto/s);
  });

  const authorizationActionCases = [
    {
      name: "new authorization",
      app: { ...baseApp, flow_status: "pending", runtime_status: "unknown" },
      label: "Generate URL",
      disabled: false,
    },
    { name: "healthy credential", app: baseApp, label: "Reauthorize", disabled: false },
    {
      name: "revoked credential",
      app: { ...baseApp, flow_status: "completed", runtime_status: "revoked" },
      label: "Restore authorization",
      disabled: false,
    },
    {
      name: "validation pending",
      app: { ...baseApp, flow_status: "validation_pending", runtime_status: "unknown" },
      label: "Validation pending",
      disabled: true,
    },
  ] satisfies ReadonlyArray<{
    name: string;
    app: OAuthAppRead;
    label: string;
    disabled: boolean;
  }>;

  it.each(authorizationActionCases)("preserves the $name authorization action", ({ app, label, disabled }) => {
    const { cells } = getTableParts(renderApps([app]));
    const button = cells[1].match(/<button([^>]*)>([^<]+)<\/button>/);

    expect(button?.[2]).toBe(label);
    expect(button?.[1].includes('disabled=""')).toBe(disabled);
  });

  it("shows managed status fields and a confirmed reauthorization action for healthy credentials", () => {
    const markup = renderApps([baseApp]);

    expect(markup).toContain("healthy");
    expect(markup).toContain("v4");
    expect(markup).toContain("1234567890ab");
    expect(markup).toContain("Reauthorize");
    expect(markup).not.toContain("1234567890abcdef1234567890abcdef");
  });

  it("shows restore action for revoked credentials", () => {
    const markup = renderApps([
      {
        ...baseApp,
        authorization_status: "revoked",
        runtime_status: "revoked",
        failure_class: "oauth_refresh_revoked",
        revoked_at: "2026-07-31T09:00:00Z",
        next_action: "reauthorize",
      },
    ]);

    expect(markup).toContain("oauth_refresh_revoked");
    expect(markup).toContain("Restore authorization");
  });

  it("disables duplicate authorization while validation is pending", () => {
    const markup = renderApps([
      {
        ...baseApp,
        authorization_status: "validation_pending",
        flow_status: "validation_pending",
        runtime_status: "unknown",
        active_credential_version: null,
        pending_credential_version: 5,
      },
    ]);

    expect(markup).toContain("Validation pending");
    expect(markup).toMatch(/<button[^>]*disabled=""[^>]*>Validation pending<\/button>/);
  });

  it("shows the health-check next action for degraded credentials without rendering secrets", () => {
    const markup = renderApps([
      {
        ...baseApp,
        runtime_status: "degraded",
        failure_class: "oauth_provider_unavailable",
        failure_count: 2,
        next_action: "run_oauth_health_check",
      },
    ]);

    expect(markup).toContain("Health check running");
    expect(markup).toContain("oauth_provider_unavailable");
    expect(markup).not.toContain("refresh_token");
    expect(markup).not.toContain("client_secret");
  });
});
