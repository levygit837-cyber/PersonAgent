import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getSkillDetail,
  installMarketplaceSkill,
  listMarketplaceSkills,
  listSkills,
  setSkillActivation,
} from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { SkillsWorkspace } from "./skills-workspace";

vi.mock("../../api/client", () => ({
  getSkillDetail: vi.fn(),
  installMarketplaceSkill: vi.fn(),
  listMarketplaceSkills: vi.fn(),
  listSkills: vi.fn(),
  setSkillActivation: vi.fn(),
}));

describe("SkillsWorkspace", () => {
  beforeEach(() => {
    vi.mocked(listSkills).mockReset();
    vi.mocked(listSkills).mockResolvedValue([
      {
        name: "Code Review",
        invocation_name: "code-review",
        slash_name: "/code-review",
        description: "Review code changes",
        source: "workspace",
        path: "/tmp/.personagent/skills/code-review/SKILL.md",
        enabled: true,
        user_invocable: true,
        model_invocable: true,
        allowed_tools: ["Read", "Grep"],
        argument_hint: "[target]",
        when_to_use: "Use for review",
        context: "inline",
      },
    ]);
    vi.mocked(listMarketplaceSkills).mockReset();
    vi.mocked(listMarketplaceSkills).mockResolvedValue([
      {
        id: "frontend-polish",
        name: "Frontend Polish",
        invocation_name: "frontend-polish",
        slash_name: "/frontend-polish",
        description: "Improve UI quality",
        allowed_tools: ["Read"],
        argument_hint: "[screen]",
        when_to_use: "Use for UI refinement",
        installed: false,
      },
    ]);
    vi.mocked(getSkillDetail).mockReset();
    vi.mocked(getSkillDetail).mockResolvedValue({
      name: "Code Review",
      invocation_name: "code-review",
      slash_name: "/code-review",
      description: "Review code changes",
      source: "workspace",
      path: "/tmp/.personagent/skills/code-review/SKILL.md",
      enabled: true,
      user_invocable: true,
      model_invocable: true,
      allowed_tools: ["Read", "Grep"],
      argument_hint: "[target]",
      when_to_use: "Use for review",
      context: "inline",
      content: "# Code Review\n\nPrioritize findings.",
      frontmatter: {},
    });
    vi.mocked(setSkillActivation).mockReset();
    vi.mocked(setSkillActivation).mockResolvedValue({ invocation_name: "code-review", enabled: false });
    vi.mocked(installMarketplaceSkill).mockReset();
    vi.mocked(installMarketplaceSkill).mockResolvedValue({
      item: {
        id: "frontend-polish",
        name: "Frontend Polish",
        invocation_name: "frontend-polish",
        slash_name: "/frontend-polish",
        description: "Improve UI quality",
        allowed_tools: ["Read"],
        argument_hint: "[screen]",
        when_to_use: "Use for UI refinement",
        installed: true,
      },
      installed_path: "/home/user/.personagent/skills/frontend-polish/SKILL.md",
    });
    useAppStore.setState({
      baseUrl: "http://localhost:8000",
      selectedWorkspace: "/tmp/project",
    });
  });

  it("renders installed skills and toggles activation", async () => {
    renderSkillsWorkspace();

    expect(await screen.findByText("Code Review")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: /disable code review/i }));

    await waitFor(() => {
      expect(setSkillActivation).toHaveBeenCalledWith(
        "http://localhost:8000",
        "code-review",
        false,
        "/tmp/project",
      );
    });
  });

  it("opens skill detail in a floating dialog", async () => {
    renderSkillsWorkspace();

    fireEvent.click(await screen.findByRole("button", { name: /view code review/i }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(await screen.findByText("Prioritize findings.")).toBeInTheDocument();
    expect(getSkillDetail).toHaveBeenCalledWith("http://localhost:8000", "code-review", "/tmp/project");
  });

  it("installs marketplace skills", async () => {
    renderSkillsWorkspace();

    expect(await screen.findByText("Frontend Polish")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /install/i }));

    await waitFor(() => {
      expect(installMarketplaceSkill).toHaveBeenCalledWith(
        "http://localhost:8000",
        "frontend-polish",
        "/tmp/project",
      );
    });
  });
});

function renderSkillsWorkspace() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <SkillsWorkspace />
    </QueryClientProvider>,
  );
}
