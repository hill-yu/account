import { describe, expect, it } from "vitest";

import {
  buildInstanceOnboardingNote,
  buildOAuthJsonImportHint,
  buildOAuthRedirectUriHint,
  buildSecondAccountChecklist,
} from "../lib/operatorGuidance";

describe("buildOAuthRedirectUriHint", () => {
  it("mentions that each account should use its own website callback", () => {
    const text = buildOAuthRedirectUriHint();

    expect(text).toContain("own website callback");
    expect(text).toContain("control plane callback");
    expect(text).toContain("do not reuse");
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
      "Generate the authorization URL, download the callback JSON from the account site, and import it in this control plane.",
    ]);
  });
});

describe("buildOAuthJsonImportHint", () => {
  it("states that callback JSON import belongs to the control plane operator flow", () => {
    const text = buildOAuthJsonImportHint();

    expect(text).toContain("control plane operator flow");
    expect(text).toContain("user_system");
    expect(text).toContain("must not");
  });
});
