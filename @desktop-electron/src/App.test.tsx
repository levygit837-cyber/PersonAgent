import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { TooltipProvider } from "./components/ui/tooltip";
import { useAppStore } from "./stores/app-store";

const originalInitialize = useAppStore.getState().initialize;

describe("App", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
    useAppStore.setState({
      initialize: async () => undefined,
      section: "openPr",
      sidebarCollapsed: true,
      selectedWorkspace: "/home/user/PersonAgent",
    });
  });

  it("renders the Open PR workspace for the openPr section", () => {
    renderApp();

    expect(screen.getByTestId("open-pr-workspace")).toBeInTheDocument();
  });

  it("renders compact mode without the sidebar shell", () => {
    window.history.pushState({}, "", "/?mode=compact");

    renderApp();

    expect(screen.getByText("Opening session...")).toBeInTheDocument();
    expect(screen.queryByText("New Chat")).not.toBeInTheDocument();
  });
});

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <App />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

afterAll(() => {
  useAppStore.setState({ initialize: originalInitialize });
  window.history.pushState({}, "", "/");
});
