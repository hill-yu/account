import { useEffect, useState } from "react";
import { RouterProvider } from "react-router-dom";

import { router } from "./router";
import { ToastProvider } from "./components/ui/ToastProvider";
import { api } from "./lib/api";
import { LoginPage } from "./pages/LoginPage";

export default function App() {
  const [sessionState, setSessionState] = useState<"checking" | "authenticated" | "unauthenticated">("checking");
  const isOAuthCallback = window.location.pathname === "/oauth/google/callback";

  useEffect(() => {
    if (isOAuthCallback) {
      return;
    }
    void api
      .getOperatorSession()
      .then(() => setSessionState("authenticated"))
      .catch(() => setSessionState("unauthenticated"));
  }, [isOAuthCallback]);

  if (isOAuthCallback) {
    return <RouterProvider router={router} />;
  }

  if (sessionState === "checking") {
    return <main className="login-page"><p>正在检查登录状态…</p></main>;
  }

  if (sessionState === "unauthenticated") {
    return <LoginPage onAuthenticated={() => setSessionState("authenticated")} />;
  }

  return (
    <ToastProvider>
      <RouterProvider router={router} />
    </ToastProvider>
  );
}

