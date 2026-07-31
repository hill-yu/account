export function buildOAuthRedirectUriHint(): string {
  return "Set redirect_uri to this account's own website callback URL. Do not default to the control plane callback, and do not reuse another account's callback URL.";
}

export function buildInstanceOnboardingNote(): string {
  return "Create a second account first, then create that account's own instance instead of attaching a second node under the first account.";
}

export function buildSecondAccountChecklist(): string[] {
  return [
    "Create the second account.",
    "Create the second account's instance.",
    "Create the second account's OAuth app.",
    "Set redirect_uri to the second account website callback.",
    "Generate the authorization URL, download the callback JSON from the account site, and import it in this control plane.",
  ];
}

export function buildOAuthJsonImportHint(): string {
  return "Upload the callback JSON in the control plane operator flow only. user_system must not host or proxy this onboarding step.";
}
