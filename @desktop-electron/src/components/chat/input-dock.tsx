import { ArrowUp, ChevronDown, ChevronRight, Command, Plus, Sparkles, Square, UsersRound } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../ui/tooltip";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { listChatCommands, listModels } from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import { useChatStore } from "../../stores/chat-store";
import { localModel, reasoningPresets, type ChatCommandInfo, type LlmModel, type ModelProvider, type ReasoningPreset } from "../../types/chat";
import { Button } from "../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

type ModelOption = {
  id: string;
  provider: ModelProvider;
  label: string;
  group: string;
  contextLength?: number;
};

const curatedHostedModels: ModelOption[] = [
  { id: "qwen/qwen3.5-397b-a17b", provider: "nvidia", label: "Qwen3.5-397B", group: "Qwen" },
  { id: "qwen/qwen3-coder-480b-a35b-instruct", provider: "nvidia", label: "Qwen3 Coder 480B", group: "Qwen" },
  { id: "minimaxai/minimax-m2.5", provider: "nvidia", label: "Minimax M2.5", group: "Minimax" },
  { id: "moonshotai/kimi-k2.5", provider: "nvidia", label: "Kimi K2.5", group: "Moonshot" },
  { id: "deepseek-ai/deepseek-v4-flash", provider: "nvidia", label: "DeepSeek V4 Flash", group: "DeepSeek" },
  { id: "deepseek-ai/deepseek-v4-pro", provider: "nvidia", label: "DeepSeek V4 Pro", group: "DeepSeek" },
  { id: "gemini-3.1-pro-preview", provider: "vertex", label: "Gemini 3.1 Pro", group: "Google Vertex" },
  { id: "gemini-3.1-pro-preview-customtools", provider: "vertex", label: "Gemini 3.1 Pro Custom Tools", group: "Google Vertex" },
  { id: "gemini-3.1-flash-lite-preview", provider: "vertex", label: "Gemini 3.1 Flash-Lite", group: "Google Vertex" },
  { id: "gemini-3.1-flash-image-preview", provider: "vertex", label: "Gemini 3.1 Flash Image", group: "Google Vertex" },
  { id: "gemini-3-flash-preview", provider: "vertex", label: "Gemini 3 Flash", group: "Google Vertex" },
  { id: "gemini-3-pro-image-preview", provider: "vertex", label: "Gemini 3 Pro Image", group: "Google Vertex" },
];

const modelGroupOrder = [
  "Local",
  "OpenAI",
  "Qwen",
  "Minimax",
  "Moonshot",
  "DeepSeek",
  "Google Vertex",
  "NVIDIA",
  "Mistral",
  "Meta",
  "Google",
  "Microsoft",
  "IBM",
  "Writer",
  "Other",
];

export function InputDock() {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const sendMessage = useChatStore((state) => state.sendMessage);
  const stopStreaming = useChatStore((state) => state.stopStreaming);
  const isStreaming = useChatStore((state) => state.isStreaming);
  const nextStepSuggestion = useChatStore((state) => state.nextStepSuggestion);
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const disabled = isStreaming;
  const slashToken = slashTokenFromText(text);
  const slashCommands = useQuery({
    queryKey: ["chat-commands", baseUrl, selectedWorkspace],
    queryFn: () => listChatCommands(baseUrl, selectedWorkspace),
    enabled: !disabled && Boolean(baseUrl) && slashToken !== null,
    staleTime: 30_000,
  });
  const commandMatches = filterSlashCommands(slashCommands.data ?? [], slashToken);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 148)}px`;
  }, [text]);

  const submit = () => {
    if (isStreaming) {
      stopStreaming();
      textareaRef.current?.focus();
      return;
    }
    const value = text.trim();
    if (!value) return;
    void sendMessage(value);
    setText("");
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center px-5 pb-5">
      <div className="pointer-events-auto w-full max-w-[780px] overflow-hidden rounded-2xl border border-glass-border/35 bg-card/90 shadow-dock ring-1 ring-primary/10 backdrop-blur-2xl">
        <ComposerAssist
          disabled={disabled}
          nextStepSuggestion={!text.trim() ? nextStepSuggestion : undefined}
          slashToken={slashToken}
          commands={commandMatches}
          onPickSuggestion={(value) => {
            if (!value.trim()) return;
            void sendMessage(value);
          }}
          onPickCommand={(command) => {
            setText(`${command.slash_name} `);
            requestAnimationFrame(() => textareaRef.current?.focus());
          }}
        />
        <div className="flex items-end gap-2 px-2.5 py-2.5 sm:gap-2.5 sm:px-3">
          <FeatureMenu enabled={!disabled} />
          <textarea
            ref={textareaRef}
            value={text}
            disabled={disabled}
            rows={1}
            placeholder="Ask the local agent..."
            onChange={(event) => setText(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            className="min-h-10 min-w-0 flex-1 resize-none bg-transparent px-1 py-2 text-[15px] leading-6 text-foreground outline-none placeholder:text-muted-foreground/80 disabled:opacity-60"
          />
          <ModelReasoningSelector enabled={!disabled} />
          <ContextWindowIndicator />
          <Button
            size="icon"
            variant={isStreaming ? "destructive" : text.trim() ? "default" : "secondary"}
            disabled={!isStreaming && !text.trim()}
            onClick={submit}
            aria-label={isStreaming ? "Stop" : "Send"}
            className="h-10 w-10 rounded-xl"
          >
            {isStreaming ? <Square className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
}

function ComposerAssist({
  disabled,
  nextStepSuggestion,
  slashToken,
  commands,
  onPickSuggestion,
  onPickCommand,
}: {
  disabled: boolean;
  nextStepSuggestion?: string;
  slashToken: string | null;
  commands: ChatCommandInfo[];
  onPickSuggestion: (value: string) => void;
  onPickCommand: (command: ChatCommandInfo) => void;
}) {
  if (disabled) return null;
  if (slashToken !== null) {
    if (commands.length === 0) return null;
    return (
      <div className="border-b border-glass-border/25 px-2 py-1.5">
        <div className="max-h-44 overflow-y-auto rounded-xl bg-background/70 p-1 text-popover-foreground">
          {commands.slice(0, 6).map((command) => (
            <button
              key={`${command.source}:${command.slash_name}`}
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                onPickCommand(command);
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-glass/80 hover:text-accent-foreground"
            >
              <Command className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{command.slash_name}</span>
                <span className="block truncate text-muted-foreground">
                  {command.argument_hint || command.description || command.source}
                </span>
              </span>
            </button>
          ))}
        </div>
      </div>
    );
  }
  if (!nextStepSuggestion) return null;
  return (
    <div className="border-b border-glass-border/25 px-2 py-1.5">
      <button
        type="button"
        onMouseDown={(event) => {
          event.preventDefault();
          onPickSuggestion(nextStepSuggestion);
        }}
        className="flex max-w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-glass/80 hover:text-accent-foreground"
      >
        <Sparkles className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{nextStepSuggestion}</span>
      </button>
    </div>
  );
}

function slashTokenFromText(value: string) {
  const trimmed = value.trimStart();
  if (!trimmed.startsWith("/") || trimmed.includes("\n")) return null;
  const token = trimmed.split(/\s+/, 1)[0];
  return token;
}

function filterSlashCommands(commands: ChatCommandInfo[], slashToken: string | null) {
  if (slashToken === null) return [];
  const normalized = slashToken.toLowerCase();
  return commands
    .filter((command) => command.user_invocable && command.slash_name.toLowerCase().startsWith(normalized))
    .sort((left, right) => left.slash_name.localeCompare(right.slash_name));
}

function FeatureMenu({ enabled }: { enabled: boolean }) {
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

function ModelReasoningSelector({ enabled }: { enabled: boolean }) {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const provider = useAppStore((state) => state.provider);
  const setProvider = useAppStore((state) => state.setProvider);
  const selectedModelId = useAppStore((state) => state.selectedModelId);
  const setSelectedModelId = useAppStore((state) => state.setSelectedModelId);
  const preset = useAppStore((state) => state.reasoningPreset);
  const setReasoningPreset = useAppStore((state) => state.setReasoningPreset);
  const localModels = useQuery({
    queryKey: ["models", baseUrl, "llama"],
    queryFn: () => listModels(baseUrl, "llama"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: 60_000,
  });
  const hostedModels = useQuery({
    queryKey: ["models", baseUrl, "nvidia"],
    queryFn: () => listModels(baseUrl, "nvidia"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: 60_000,
  });
  const vertexModels = useQuery({
    queryKey: ["models", baseUrl, "vertex"],
    queryFn: () => listModels(baseUrl, "vertex"),
    enabled: enabled && Boolean(baseUrl),
    staleTime: 60_000,
  });
  const modelOptions = buildModelOptions(localModels.data, hostedModels.data, vertexModels.data);
  const selectedOption =
    modelOptions.find((item) => item.provider === provider && item.id === selectedModelId) ??
    modelOptions.find((item) => item.id === selectedModelId) ??
    toModelOption({ ...localModel, id: selectedModelId || localModel.id, name: selectedModelId || localModel.name, provider }, provider);
  const groupedModels = groupModelOptions(modelOptions);

  const selectModel = (option: ModelOption) => {
    if (option.provider !== provider) setProvider(option.provider);
    setSelectedModelId(option.id);
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
                  >
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

function buildModelOptions(localModels?: LlmModel[], hostedModels?: LlmModel[], vertexModels?: LlmModel[]) {
  const byKey = new Map<string, ModelOption>();
  const add = (option: ModelOption) => {
    byKey.set(`${option.provider}:${option.id}`, option);
  };

  for (const model of localModels?.length ? localModels : [localModel]) {
    add(toModelOption(model, "llama"));
  }
  for (const model of curatedHostedModels) {
    add(model);
  }
  for (const model of hostedModels ?? []) {
    add(toModelOption(model, "nvidia"));
  }
  for (const model of vertexModels ?? []) {
    add(toModelOption(model, "vertex"));
  }

  return [...byKey.values()];
}

function groupModelOptions(options: ModelOption[]) {
  const groups = new Map<string, ModelOption[]>();
  for (const option of options) {
    const group = groups.get(option.group) ?? [];
    group.push(option);
    groups.set(option.group, group);
  }

  return [...groups.entries()]
    .sort(([left], [right]) => groupRank(left) - groupRank(right) || left.localeCompare(right))
    .map(([name, items]) => ({ name, items: items.sort((left, right) => left.label.localeCompare(right.label)) }));
}

function groupRank(group: string) {
  const index = modelGroupOrder.indexOf(group);
  return index === -1 ? modelGroupOrder.length : index;
}

function toModelOption(model: LlmModel, fallbackProvider: ModelProvider): ModelOption {
  const provider = model.provider || fallbackProvider;
  const id = model.id || localModel.id;
  return {
    id,
    provider,
    label: formatModelLabel(model.name || id),
    group: modelGroup(id, provider),
    contextLength: model.context_length,
  };
}

function modelGroup(id: string, provider: ModelProvider) {
  const normalized = id.toLowerCase();
  if (provider === "llama") return "Local";
  if (provider === "vertex") return "Google Vertex";
  if (normalized.startsWith("openai/") || normalized.startsWith("gpt-")) return "OpenAI";
  if (normalized.startsWith("qwen/")) return "Qwen";
  if (normalized.startsWith("minimax") || normalized.startsWith("minimaxai/")) return "Minimax";
  if (normalized.startsWith("moonshotai/")) return "Moonshot";
  if (normalized.startsWith("deepseek-ai/")) return "DeepSeek";
  if (normalized.startsWith("nvidia/")) return "NVIDIA";
  if (normalized.startsWith("mistralai/") || normalized.startsWith("nv-mistralai/")) return "Mistral";
  if (normalized.startsWith("meta/")) return "Meta";
  if (normalized.startsWith("google/")) return "Google";
  if (normalized.startsWith("microsoft/")) return "Microsoft";
  if (normalized.startsWith("ibm/")) return "IBM";
  if (normalized.startsWith("writer/")) return "Writer";
  if (normalized.includes("/")) return formatVendorLabel(normalized.split("/", 1)[0]);
  return "Other";
}

function formatModelLabel(value: string) {
  const normalized = value.trim();
  if (!normalized || normalized === "local-model" || normalized.toLowerCase() === "local model") return "Local";
  const exact: Record<string, string> = {
    "qwen/qwen3.5-397b-a17b": "Qwen3.5-397B",
    "qwen/qwen3-coder-480b-a35b-instruct": "Qwen3 Coder 480B",
    "minimaxai/minimax-m2.5": "Minimax M2.5",
    "moonshotai/kimi-k2.5": "Kimi K2.5",
    "deepseek-ai/deepseek-v4-flash": "DeepSeek V4 Flash",
    "deepseek-ai/deepseek-v4-pro": "DeepSeek V4 Pro",
    "nvidia/nemotron-3-nano-30b-a3b": "Nemotron 3 Nano 30B",
    "gemini-3.1-pro-preview": "Gemini 3.1 Pro",
    "gemini-3.1-pro-preview-customtools": "Gemini 3.1 Pro Custom Tools",
    "gemini-3.1-flash-lite-preview": "Gemini 3.1 Flash-Lite",
    "gemini-3.1-flash-image-preview": "Gemini 3.1 Flash Image",
    "gemini-3-flash-preview": "Gemini 3 Flash",
    "gemini-3-pro-image-preview": "Gemini 3 Pro Image",
  };
  if (exact[normalized]) return exact[normalized];

  const leaf = normalized.includes("/") ? normalized.split("/").at(-1) || normalized : normalized;
  const brandNames: Record<string, string> = {
    ai: "AI",
    deepseek: "DeepSeek",
    gpt: "GPT",
    gemini: "Gemini",
    kimi: "Kimi",
    llama: "Llama",
    minimax: "Minimax",
    mistral: "Mistral",
    nemotron: "Nemotron",
    oss: "OSS",
    qwen: "Qwen",
  };
  return leaf
    .replace(/[-_]+/g, " ")
    .replace(/\b(gpt|oss|qwen|kimi|mistral|llama|nemotron|deepseek|minimax|gemini|ai)\b/gi, (part) => brandNames[part.toLowerCase()])
    .replace(/\b(qwen|gpt|kimi|llama)(?=\d)/gi, (part) => brandNames[part.toLowerCase()])
    .replace(/\b([0-9]+)b\b/gi, "$1B")
    .replace(/\b([0-9]+)k\b/gi, "$1K")
    .replace(/\s+/g, " ")
    .trim();
}

function ContextWindowIndicator() {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const provider = useAppStore((state) => state.provider);
  const selectedModelId = useAppStore((state) => state.selectedModelId);
  const messages = useChatStore((state) => state.messages);
  const liveSessionUsage = useChatStore((state) => state.liveSessionUsage);

  const localModels = useQuery({
    queryKey: ["models", baseUrl, "llama"],
    queryFn: () => listModels(baseUrl, "llama"),
    enabled: Boolean(baseUrl),
    staleTime: 60_000,
  });
  const hostedModels = useQuery({
    queryKey: ["models", baseUrl, "nvidia"],
    queryFn: () => listModels(baseUrl, "nvidia"),
    enabled: Boolean(baseUrl),
    staleTime: 60_000,
  });
  const vertexModels = useQuery({
    queryKey: ["models", baseUrl, "vertex"],
    queryFn: () => listModels(baseUrl, "vertex"),
    enabled: Boolean(baseUrl),
    staleTime: 60_000,
  });

  const modelOptions = buildModelOptions(localModels.data, hostedModels.data, vertexModels.data);
  const selectedOption =
    modelOptions.find((item) => item.provider === provider && item.id === selectedModelId) ??
    modelOptions.find((item) => item.id === selectedModelId);

  const contextLength = selectedOption?.contextLength ?? 131072; // 128K default

  const usedTokens = useMemo(() => {
    const fromMessages = messages.reduce((acc, msg) => {
      const contentTokens = msg.content ? Math.max(1, Math.ceil(msg.content.length / 4)) : 0;
      const reasoningTokens = msg.reasoning ? Math.max(1, Math.ceil(msg.reasoning.length / 4)) : 0;
      return acc + contentTokens + reasoningTokens;
    }, 0);
    const fromLive = liveSessionUsage.agent_output_tokens.value + liveSessionUsage.thinking_output_tokens.value;
    // Use the larger estimate to account for streaming content not yet flushed into messages
    return Math.max(fromMessages, fromLive);
  }, [messages, liveSessionUsage]);

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

function formatVendorLabel(value: string) {
  const exact: Record<string, string> = {
    "01-ai": "01.AI",
    ai21labs: "AI21 Labs",
    baai: "BAAI",
    bigcode: "BigCode",
    bytedance: "ByteDance",
    sarvamai: "SarvamAI",
    "stepfun-ai": "StepFun",
    "z-ai": "Z.ai",
  };
  if (exact[value]) return exact[value];

  return value
    .replace(/[-_]+/g, " ")
    .replace(/\b(ai|ibm|baai)\b/gi, (part) => part.toUpperCase())
    .replace(/\b\w/g, (part) => part.toUpperCase())
    .trim();
}
