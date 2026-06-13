export function buildOAuthRedirectUriHint(): string {
  return "Set the redirect URI to the current account's own website callback. Different accounts can use different website addresses. Do not reuse another account's callback URL.";
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
    "Generate the authorization URL and complete authorization.",
  ];
}
