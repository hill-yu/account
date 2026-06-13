import { describe, expect, it } from "vitest";

import {
  buildInstanceOnboardingNote,
  buildOAuthRedirectUriHint,
  buildSecondAccountChecklist,
} from "../lib/operatorGuidance";

describe("buildOAuthRedirectUriHint", () => {
  it("mentions that each account should use its own website callback", () => {
    const text = buildOAuthRedirectUriHint();

    expect(text).toContain("current account");
    expect(text).toContain("own website");
    expect(text).toContain("Do not reuse");
  });
});

describe("buildInstanceOnboardingNote", () => {
  it("explains that the second node belongs under a second account", () => {
    expect(buildInstanceOnboardingNote()).toContain("Create a second account first");
  });
});

describe("buildSecondAccountChecklist", () => {
  it("returns the five-step second-account onboarding checklist", () => {
    expect(buildSecondAccountChecklist()).toEqual([
      "Create the second account.",
      "Create the second account's instance.",
      "Create the second account's OAuth app.",
      "Set redirect_uri to the second account website callback.",
      "Generate the authorization URL and complete authorization.",
    ]);
  });
});
