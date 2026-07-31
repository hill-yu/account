import { createBrowserRouter } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { OAuthCallbackPage } from "./pages/OAuthCallbackPage";
import { OperationsPage } from "./pages/OperationsPage";
import { ReportsPage } from "./pages/ReportsPage";

export const router = createBrowserRouter([
  {
    path: "/oauth/google/callback",
    element: <OAuthCallbackPage />,
  },
  {
    path: "/",
    element: <AppShell />,
    children: [
      {
        index: true,
        element: <OperationsPage />,
      },
      {
        path: "reports",
        element: <ReportsPage />,
      },
    ],
  },
]);
