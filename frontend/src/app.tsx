import { Router } from "@solidjs/router";
import { FileRoutes } from "@solidjs/start/router";
import { Suspense } from "solid-js";
import { ThemeProvider } from "~/ui";
import { usePageTitle } from "~/app/usePageTitle";
import "./app.css";

/**
 * Root: theme bootstrap + per-route document title + Suspense. Per-section
 * chrome (app shell vs bare auth) is applied by the route-group layout files in
 * src/routes, not here.
 */
export default function App() {
  return (
    <Router
      root={(props) => {
        usePageTitle();
        return (
          <ThemeProvider>
            <Suspense>{props.children}</Suspense>
          </ThemeProvider>
        );
      }}
    >
      <FileRoutes />
    </Router>
  );
}
