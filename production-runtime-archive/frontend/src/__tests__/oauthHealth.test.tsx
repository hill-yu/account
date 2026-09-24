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


describe("OAuthAppsSection health state", () => {
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
