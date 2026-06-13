import type { OAuthCallbackResponse } from "../types/api";

const OAUTH_CALLBACK_PREFIX = "oauth-callback:";

export function buildOAuthCallbackRedirectUri(origin: string): string {
  return `${origin.replace(/\/$/, "")}/oauth/google/callback`;
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
