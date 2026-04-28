import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { App } from "./App";
import { TooltipProvider } from "./components/ui/tooltip";
import { useAppStore } from "./stores/app-store";

const originalInitialize = useAppStore.getState().initialize;

describe("App", () => {
  beforeEach(() => {
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
});
