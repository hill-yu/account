import { describe, expect, it } from "vitest";

import {
  buildOAuthCallbackFingerprint,
  buildOAuthCallbackRedirectUri,
  describeOAuthCallbackResult,
  shouldSkipOAuthCallback,
} from "../lib/oauth";

describe("buildOAuthCallbackRedirectUri", () => {
  it("builds a frontend callback path from the current origin", () => {
    expect(buildOAuthCallbackRedirectUri("http://127.0.0.1:4173")).toBe("http://127.0.0.1:4173/oauth/google/callback");
  });
});

describe("describeOAuthCallbackResult", () => {
  it("returns success copy when refresh token is present", () => {
    expect(
      describeOAuthCallbackResult({
        authorization_status: "authorized",
        refresh_token_present: true,
        oauth_app_id: 1,
        account_id: 2,
      }),
    ).toBe("授权已完成，refresh token 已保存。");
  });

  it("returns a warning copy when authorization finishes without refresh token", () => {
    expect(
      describeOAuthCallbackResult({
        authorization_status: "authorized",
        refresh_token_present: false,
        oauth_app_id: 1,
        account_id: 2,
      }),
    ).toBe("授权已完成，但当前没有拿到 refresh token，请检查 Google OAuth 配置。");
  });
});

describe("shouldSkipOAuthCallback", () => {
  it("allows the first callback request and blocks duplicates", () => {
    const storage = new Map<string, string>();
    const fingerprint = buildOAuthCallbackFingerprint("state-1", "code-1");

    expect(shouldSkipOAuthCallback(storageLike(storage), fingerprint)).toBe(false);
    expect(shouldSkipOAuthCallback(storageLike(storage), fingerprint)).toBe(true);
  });
});

function storageLike(storage: Map<string, string>): Storage {
  return {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => {
      storage.set(key, value);
    },
    removeItem: (key) => {
      storage.delete(key);
    },
    clear: () => {
      storage.clear();
    },
    key: (index) => Array.from(storage.keys())[index] ?? null,
    get length() {
      return storage.size;
    },
  } as Storage;
}
