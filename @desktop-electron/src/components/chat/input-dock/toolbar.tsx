import { Brain, ChevronDown, ChevronRight, LogOut, Plus, UsersRound } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { getCodexAuthStatus, listModels, logoutCodex } from "../../../api/client";
import { useAppStore } from "../../../stores/app-store";
import { useChatStore } from "../../../stores/chat-store";
import { localModel, reasoningPresets, type ReasoningPreset } from "../../../types/chat";
import { Button } from "../../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../../ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../../ui/tooltip";
import {
  type ModelOption,
  MODEL_CATALOG_STALE_MS,
  CODEX_AUTH_STALE_MS,
  providerIconUrl,
  toModelOption,
  buildModelOptions,
  groupModelOptions,
} from "./helpers";

export function ProviderIcon({ group, className }: { group: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  const url = providerIconUrl(group);

  useEffect(() => {
    setFailed(false);
  }, [url]);

  if (!url || failed) {
    return <Brain className={className || "h-3.5 w-3.5 shrink-0 text-muted-foreground/70"} />;
  }
  return (
    <img
      key={url}
      src={url}
      alt=""
      className={className || "h-3.5 w-3.5 shrink-0 object-contain"}
      onError={() => setFailed(true)}
    />
  );
}

export function FeatureMenu({ enabled }: { enabled: boolean }) {
  const teamMode = useAppStore((state) => state.teamMode);
  const setTeamMode = useAppStore((state) => state.setTeamMode);
  const agentsBranchRef = useRef<HTMLDivElement | null>(null);
  const agentsCloseTimerRef = useRef<number | null>(null);
  const [agentsOpen, setAgentsOpen] = useState(false);
  const clearAgentsCloseTimer = () => {
    if (agentsCloseTimerRef.current) {
      window.clearTimeout(agentsCloseTimerRef.current);
      agentsCloseTimerRef.current = null;
    }
  };
  const openAgents = () => {
    clearAgentsCloseTimer();
    setAgentsOpen(true);
  };
  const scheduleAgentsClose = () => {
    clearAgentsCloseTimer();
    agentsCloseTimerRef.current = window.setTimeout(() => {
      setAgentsOpen(false);
      agentsCloseTimerRef.current = null;
    }, 180);
  };

  useEffect(() => clearAgentsCloseTimer, []);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          disabled={!enabled}
          aria-label="System features"
          title="System features"
          className="h-10 w-10 shrink-0 rounded-xl text-muted-foreground hover:text-foreground"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side="top"
        align="start"
        className="personagent-dropdown-fade personagent-feature-menu w-56 overflow-visible"
      >
        <DropdownMenuLabel>Features</DropdownMenuLabel>
        <div
          ref={agentsBranchRef}
          className="personagent-feature-branch relative"
          onPointerEnter={openAgents}
          onPointerLeave={scheduleAgentsClose}
          onFocus={openAgents}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              scheduleAgentsClose();
            }
          }}
        >
          <DropdownMenuItem
            aria-haspopup="menu"
            aria-expanded={agentsOpen}
            onSelect={(event) => event.preventDefault()}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                setAgentsOpen(true);
              }
            }}
            className="h-8 justify-between gap-2"
          >
            <span className="flex min-w-0 items-center gap-2">
              <UsersRound className="h-3.5 w-3.5 text-muted-foreground" />
              <span>Agentes</span>
            </span>
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          </DropdownMenuItem>
          <div
            aria-hidden={!agentsOpen}
            className={[
              "personagent-feature-submenu-panel absolute bottom-0 left-[calc(100%+8px)] z-50 w-52 rounded-xl border",
              "border-glass-border/35 bg-popover/95 p-1 text-popover-foreground shadow-floating backdrop-blur-xl",
              agentsOpen ? "is-open" : "",
            ].join(" ")}
          >
            <DropdownMenuItem
              role="menuitemcheckbox"
              aria-checked={teamMode}
              onSelect={(event) => {
                event.preventDefault();
                setTeamMode(!teamMode);
              }}
              className="flex h-8 w-full cursor-default items-center justify-between gap-3 px-2 text-xs"
            >
              <span className="flex min-w-0 items-center gap-2">
                <UsersRound className="h-3.5 w-3.5 text-muted-foreground" />
                <span>Teams</span>
              </span>
              <span
                aria-hidden="true"
                className={[
                  "relative h-4 w-7 shrink-0 rounded-full transition-colors",
                  teamMode ? "bg-primary" : "bg-muted-foreground/[0.35]",
                ].join(" ")}
              >
                <span
                  className={[
                    "absolute left-0.5 top-0.5 h-3 w-3 rounded-full bg-foreground shadow-sm transition-transform",
                    teamMode ? "translate-x-3.5" : "translate-x-0",
                  ].join(" ")}
                />
              </span>
            </DropdownMenuItem>
          </div>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ModelReasoningSelector({ enabled }: { enabled: boolean }) {
  const queryClient = useQueryClient();
  const baseUrl = useAppStore((state) => state.baseUrl);
  const provider = useAppStore((state) => state.provider);
  const setProvider = useAppStore((state) => state.setProvider);
  const selectedModelId = useAppStore((state) => state.selectedModelId);
  const setSelectedModelId = useAppStore((state) => state.setSelectedModelId);
  const preset = useAppStore((state) => state.reasoningPreset);
  const setReasoningPreset = useAppStore((state) => state.setReasoningPreset);
  const [codexLogoutPending, setCodexLogoutPending] = useState(false);
  const localModels = useQuery({
    queryKey: ["models", baseUrl, "llama"],
    queryFn: () => listModels(baseUrl, "llama"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const hostedModels = useQuery({
    queryKey: ["models", baseUrl, "nvidia"],
    queryFn: () => listModels(baseUrl, "nvidia"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const deepSeekModels = useQuery({
    queryKey: ["models", baseUrl, "deepseek"],
    queryFn: () => listModels(baseUrl, "deepseek"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const zenMuxModels = useQuery({
    queryKey: ["models", baseUrl, "zenmux"],
    queryFn: () => listModels(baseUrl, "zenmux"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const vertexModels = useQuery({
    queryKey: ["models", baseUrl, "vertex"],
    queryFn: () => listModels(baseUrl, "vertex"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const kimiModels = useQuery({
    queryKey: ["models", baseUrl, "kimi"],
    queryFn: () => listModels(baseUrl, "kimi"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const codexModels = useQuery({
    queryKey: ["models", baseUrl, "codex"],
    queryFn: () => listModels(baseUrl, "codex"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const codexAuth = useQuery({
    queryKey: ["codex-auth", baseUrl],
    queryFn: () => getCodexAuthStatus(baseUrl),
    enabled: enabled && Boolean(baseUrl),
    staleTime: CODEX_AUTH_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const modelOptions = buildModelOptions(
    localModels.data,
    hostedModels.data,
    deepSeekModels.data,
    zenMuxModels.data,
    vertexModels.data,
    kimiModels.data,
    codexModels.data,
  );
  const selectedOption =
    modelOptions.find((item) => item.provider === provider && item.id === selectedModelId) ??
    modelOptions.find((item) => item.id === selectedModelId) ??
    toModelOption({ ...localModel, id: selectedModelId || localModel.id, name: selectedModelId || localModel.name, provider }, provider);
  const groupedModels = groupModelOptions(modelOptions);

  const selectModel = (option: ModelOption) => {
    if (option.provider !== provider) setProvider(option.provider);
    setSelectedModelId(option.id);
  };
  const handleCodexLogout = async (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setCodexLogoutPending(true);
    try {
      await logoutCodex(baseUrl);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["codex-auth", baseUrl] }),
        queryClient.invalidateQueries({ queryKey: ["models", baseUrl, "codex"] }),
      ]);
    } finally {
      setCodexLogoutPending(false);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="subtle"
          size="default"
          disabled={!enabled}
          aria-label="Model and reasoning"
          className="h-10 min-w-[112px] max-w-[180px] shrink-0 justify-between gap-2 rounded-xl border-glass-border/35 bg-background/[0.45] px-3 text-xs shadow-soft hover:border-glass-border/50 hover:bg-glass/80 sm:max-w-[220px]"
        >
          <ProviderIcon key={selectedOption.group} group={selectedOption.group} className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{selectedOption.label}</span>
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="end" className="personagent-dropdown-fade w-72 rounded-2xl">
        <DropdownMenuLabel>Reasoning</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={preset} onValueChange={(value) => setReasoningPreset(value as ReasoningPreset)}>
          {reasoningPresets.map((item) => (
            <DropdownMenuRadioItem key={item.value} value={item.value}>
              {item.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <div className="px-2 py-1.5">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="flex min-w-0 items-center gap-2 font-medium">
              <ProviderIcon group="ChatGPT Subscription" />
              <span className="truncate">ChatGPT Subscription</span>
            </span>
            <span className={codexAuth.data?.authenticated ? "text-emerald-400" : "text-muted-foreground"}>
              {codexAuth.isLoading
                ? "Checking"
                : codexAuth.data?.authenticated
                  ? "Connected"
                  : "Disconnected"}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
            <span className="min-w-0 truncate">
              {codexAuth.data?.authenticated
                ? codexAuth.data.email || codexAuth.data.account_id || "Codex CLI"
                : codexAuth.data?.error || "Run codex login"}
            </span>
            <button
              type="button"
              disabled={codexLogoutPending || !codexAuth.data?.authenticated}
              onClick={handleCodexLogout}
              className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-muted-foreground hover:bg-glass/70 hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
            >
              <LogOut className="h-3 w-3" />
              Logout
            </button>
          </div>
        </div>
        <DropdownMenuSeparator />
        <div className="max-h-72 overflow-y-auto">
          {groupedModels.map((group, index) => (
            <div key={group.name}>
              {index > 0 ? <DropdownMenuSeparator /> : null}
              <DropdownMenuLabel>{group.name}</DropdownMenuLabel>
              <DropdownMenuRadioGroup value={`${provider}:${selectedModelId}`}>
                {group.items.map((model) => (
                  <DropdownMenuRadioItem
                    key={`${model.provider}:${model.id}`}
                    value={`${model.provider}:${model.id}`}
                    onSelect={() => selectModel(model)}
                    className="gap-2"
                  >
                    <ProviderIcon group={model.group} />
                    <span className="truncate">{model.label}</span>
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </div>
          ))}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ContextWindowIndicator() {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const provider = useAppStore((state) => state.provider);
  const selectedModelId = useAppStore((state) => state.selectedModelId);
  const contextTokenEstimate = useChatStore((state) => state.contextTokenEstimate);
  const contextWindowEstimate = useChatStore((state) => state.contextWindowEstimate);
  const liveSessionUsage = useChatStore((state) => state.liveSessionUsage);

  const localModels = useQuery({
    queryKey: ["models", baseUrl, "llama"],
    queryFn: () => listModels(baseUrl, "llama"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const hostedModels = useQuery({
    queryKey: ["models", baseUrl, "nvidia"],
    queryFn: () => listModels(baseUrl, "nvidia"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const deepSeekModels = useQuery({
    queryKey: ["models", baseUrl, "deepseek"],
    queryFn: () => listModels(baseUrl, "deepseek"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const zenMuxModels = useQuery({
    queryKey: ["models", baseUrl, "zenmux"],
    queryFn: () => listModels(baseUrl, "zenmux"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const vertexModels = useQuery({
    queryKey: ["models", baseUrl, "vertex"],
    queryFn: () => listModels(baseUrl, "vertex"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const kimiModels = useQuery({
    queryKey: ["models", baseUrl, "kimi"],
    queryFn: () => listModels(baseUrl, "kimi"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });
  const codexModels = useQuery({
    queryKey: ["models", baseUrl, "codex"],
    queryFn: () => listModels(baseUrl, "codex"),
    enabled: Boolean(baseUrl),
    staleTime: MODEL_CATALOG_STALE_MS,
    refetchOnWindowFocus: false,
  });

  const modelOptions = buildModelOptions(
    localModels.data,
    hostedModels.data,
    deepSeekModels.data,
    zenMuxModels.data,
    vertexModels.data,
    kimiModels.data,
    codexModels.data,
  );
  const selectedOption =
    modelOptions.find((item) => item.provider === provider && item.id === selectedModelId) ??
    modelOptions.find((item) => item.id === selectedModelId);

  const contextLength = contextWindowEstimate ?? selectedOption?.contextLength ?? 131072;

  const usedTokens = useMemo(() => {
    const promptContext = Math.max(
      contextTokenEstimate,
      liveSessionUsage.context_tokens.value,
    );
    const liveGenerated =
      liveSessionUsage.agent_output_tokens.value + liveSessionUsage.thinking_output_tokens.value;
    return Math.max(contextTokenEstimate, promptContext + liveGenerated);
  }, [contextTokenEstimate, liveSessionUsage]);

  const totalK = Math.round(contextLength / 1024);
  const usedK = Math.ceil(usedTokens / 1024);
  const usageRatio = Math.min(1, usedTokens / contextLength);
  const remainingPct = Math.max(0, Math.min(100, Math.round((1 - usageRatio) * 100)));

  const radius = 8;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - usageRatio);

  let color = "text-emerald-400";
  if (usageRatio > 0.9) color = "text-red-400";
  else if (usageRatio > 0.7) color = "text-amber-400";
  else if (usageRatio > 0.5) color = "text-yellow-400";

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex h-10 w-10 shrink-0 cursor-default items-center justify-center rounded-xl hover:bg-glass/60">
            <svg width="20" height="20" viewBox="0 0 20 20" className="-rotate-90">
              <circle
                cx="10"
                cy="10"
                r={radius}
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                className="text-muted-foreground/20"
              />
              <circle
                cx="10"
                cy="10"
                r={radius}
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={dashOffset}
                className={color}
              />
            </svg>
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" align="center" className="text-center">
          <div className="leading-relaxed">
            <div className="text-[11px] text-muted-foreground">
              {remainingPct}%
            </div>
            <div className="text-[11px] font-medium text-foreground">
              {usedK}K/{totalK}K Contexto
            </div>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
