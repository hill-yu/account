import type { OAuthCallbackImportRequest, OAuthCallbackResponse } from "../types/api";

const OAUTH_CALLBACK_PREFIX = "oauth-callback:";

export function buildOAuthCallbackRedirectUri(origin: string): string {
  return `${origin.replace(/\/$/, "")}/oauth/google/callback`;
}

function asNonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function parseOAuthCallbackImportJson(text: string): OAuthCallbackImportRequest {
  const raw = JSON.parse(text) as Record<string, unknown>;

  const state = asNonEmptyString(raw.state);
  const code = asNonEmptyString(raw.code);
  const redirectUri = asNonEmptyString(raw.redirect_uri);
  const callbackUrl = asNonEmptyString(raw.callback_url);

  if (!state || !code || !redirectUri || !callbackUrl) {
    throw new Error("Callback JSON is missing one or more required fields.");
  }

  return {
    state,
    code,
    redirect_uri: redirectUri,
    callback_url: callbackUrl,
    scope: asNonEmptyString(raw.scope),
    iss: asNonEmptyString(raw.iss),
    error: asNonEmptyString(raw.error),
    downloaded_at: asNonEmptyString(raw.downloaded_at),
  };
}

export function buildOAuthCallbackFingerprint(state: string, code: string): string {
  return `${OAUTH_CALLBACK_PREFIX}${state}:${code}`;
}

export function shouldSkipOAuthCallback(storage: Storage, fingerprint: string): boolean {
  if (storage.getItem(fingerprint) === "handled") {
    return true;
  }

  storage.setItem(fingerprint, "handled");
  return false;
}

export function describeOAuthCallbackResult(result: OAuthCallbackResponse): string {
  if (result.authorization_status === "authorized" && result.refresh_token_present) {
    return "授权已完成，refresh token 已保存。";
  }

  if (result.authorization_status === "authorized" && !result.refresh_token_present) {
    return "授权已完成，但当前没有拿到 refresh token，请检查 Google OAuth 配置。";
  }

  return "授权流程已返回，但状态不是已授权，请回到控制台检查详情。";
}
