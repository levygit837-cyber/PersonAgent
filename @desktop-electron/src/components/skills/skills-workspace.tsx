import { useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Eye, Loader2, Search, Sparkles, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getSkillDetail,
  installMarketplaceSkill,
  listMarketplaceSkills,
  listSkills,
  setSkillActivation,
} from "../../api/client";
import { useAppStore } from "../../stores/app-store";
import type { SkillMarketplaceItem, SkillSummary } from "../../types/chat";
import { Button } from "../ui/button";

export function SkillsWorkspace() {
  const baseUrl = useAppStore((state) => state.baseUrl);
  const selectedWorkspace = useAppStore((state) => state.selectedWorkspace);
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<string | undefined>();

  const skillsQuery = useQuery({
    queryKey: ["skills", baseUrl, selectedWorkspace],
    queryFn: () => listSkills(baseUrl, selectedWorkspace),
    enabled: Boolean(baseUrl),
    staleTime: 30_000,
  });
  const marketplaceQuery = useQuery({
    queryKey: ["skills-marketplace", baseUrl, selectedWorkspace],
    queryFn: () => listMarketplaceSkills(baseUrl, selectedWorkspace),
    enabled: Boolean(baseUrl),
    staleTime: 30_000,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ skill, enabled }: { skill: SkillSummary; enabled: boolean }) =>
      setSkillActivation(baseUrl, skill.invocation_name, enabled, selectedWorkspace),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["skills"] }),
        queryClient.invalidateQueries({ queryKey: ["chat-commands"] }),
      ]);
    },
  });

  const installMutation = useMutation({
    mutationFn: (item: SkillMarketplaceItem) => installMarketplaceSkill(baseUrl, item.id, selectedWorkspace),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["skills"] }),
        queryClient.invalidateQueries({ queryKey: ["skills-marketplace"] }),
        queryClient.invalidateQueries({ queryKey: ["chat-commands"] }),
      ]);
    },
  });

  const filteredSkills = useMemo(
    () => filterSkills(skillsQuery.data ?? [], query),
    [query, skillsQuery.data],
  );
  const filteredMarketplace = useMemo(
    () => filterMarketplace(marketplaceQuery.data ?? [], query),
    [marketplaceQuery.data, query],
  );
  const activeCount = (skillsQuery.data ?? []).filter((skill) => skill.enabled).length;

  return (
    <section className="flex h-full min-w-0 flex-col overflow-hidden bg-background">
      <header className="flex h-10 shrink-0 items-center gap-3 border-b border-glass-border/25 bg-background/95 px-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary" />
          <span className="min-w-0 truncate text-sm font-medium text-foreground">Skills</span>
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
            {activeCount} active
          </span>
        </div>
        <label className="relative block w-[min(340px,42vw)]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search skills"
            className="h-7 w-full rounded-xl border border-glass-border/35 bg-card/80 pl-8 pr-3 text-xs text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/45"
          />
        </label>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        <div className="mx-auto grid w-full max-w-6xl gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
          <section className="min-w-0">
            <SectionHeader title="Installed Skills" count={filteredSkills.length} />
            <div className="mt-3 grid gap-2">
              {skillsQuery.isLoading ? <LoadingRow label="Loading installed skills" /> : null}
              {skillsQuery.isError ? <ErrorRow label="Installed skills unavailable" /> : null}
              {!skillsQuery.isLoading && !skillsQuery.isError && filteredSkills.length === 0 ? (
                <EmptyRow label="No installed skills match this search." />
              ) : null}
              {filteredSkills.map((skill) => (
                <InstalledSkillRow
                  key={`${skill.source}:${skill.invocation_name}:${skill.path}`}
                  skill={skill}
                  pending={toggleMutation.isPending && toggleMutation.variables?.skill.invocation_name === skill.invocation_name}
                  onToggle={() => toggleMutation.mutate({ skill, enabled: !skill.enabled })}
                  onDetails={() => setSelectedSkill(skill.invocation_name)}
                />
              ))}
            </div>
          </section>

          <section className="min-w-0">
            <SectionHeader title="Marketplace" count={filteredMarketplace.length} />
            <div className="mt-3 grid gap-2">
              {marketplaceQuery.isLoading ? <LoadingRow label="Loading marketplace" /> : null}
              {marketplaceQuery.isError ? <ErrorRow label="Marketplace unavailable" /> : null}
              {!marketplaceQuery.isLoading && !marketplaceQuery.isError && filteredMarketplace.length === 0 ? (
                <EmptyRow label="No marketplace skills match this search." />
              ) : null}
              {filteredMarketplace.map((item) => (
                <MarketplaceSkillRow
                  key={item.id}
                  item={item}
                  pending={installMutation.isPending && installMutation.variables?.id === item.id}
                  onInstall={() => installMutation.mutate(item)}
                />
              ))}
            </div>
          </section>
        </div>
      </div>

      <SkillDetailDialog
        invocationName={selectedSkill}
        open={Boolean(selectedSkill)}
        onOpenChange={(open) => {
          if (!open) setSelectedSkill(undefined);
        }}
        baseUrl={baseUrl}
        workspaceRoot={selectedWorkspace}
      />
    </section>
  );
}

function SectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-center gap-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">{title}</h2>
      <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-muted-foreground">
        {count}
      </span>
    </div>
  );
}

function InstalledSkillRow({
  skill,
  pending,
  onToggle,
  onDetails,
}: {
  skill: SkillSummary;
  pending: boolean;
  onToggle: () => void;
  onDetails: () => void;
}) {
  return (
    <article className="rounded-xl border border-glass-border/30 bg-card/70 p-3 shadow-soft">
      <div className="flex min-w-0 items-start gap-3">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
          <Sparkles className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <h3 className="truncate text-sm font-medium text-foreground">{skill.name}</h3>
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-widest text-muted-foreground">
              {sourceLabel(skill.source)}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {skill.description || "Local skill"}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
            <span className="rounded-full bg-background/60 px-1.5 py-0.5 font-mono">{skill.slash_name}</span>
            {skill.allowed_tools.slice(0, 3).map((tool) => (
              <span key={tool} className="rounded-full bg-background/60 px-1.5 py-0.5">
                {tool}
              </span>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Button variant="ghost" size="iconSm" aria-label={`View ${skill.name}`} onClick={onDetails}>
            <Eye className="h-3.5 w-3.5" />
          </Button>
          <SkillToggle skill={skill} pending={pending} onToggle={onToggle} />
        </div>
      </div>
    </article>
  );
}

function SkillToggle({
  skill,
  pending,
  onToggle,
}: {
  skill: SkillSummary;
  pending: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={skill.enabled}
      aria-label={`${skill.enabled ? "Disable" : "Enable"} ${skill.name}`}
      disabled={pending}
      onClick={onToggle}
      className={[
        "relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50",
        skill.enabled ? "bg-primary" : "bg-muted-foreground/[0.35]",
      ].join(" ")}
    >
      <span
        className={[
          "absolute left-0.5 top-0.5 grid h-4 w-4 place-items-center rounded-full bg-foreground shadow-sm transition-transform",
          skill.enabled ? "translate-x-4" : "translate-x-0",
        ].join(" ")}
      >
        {pending ? <Loader2 className="h-2.5 w-2.5 animate-spin text-background" /> : null}
      </span>
    </button>
  );
}

function MarketplaceSkillRow({
  item,
  pending,
  onInstall,
}: {
  item: SkillMarketplaceItem;
  pending: boolean;
  onInstall: () => void;
}) {
  return (
    <article className="rounded-xl border border-glass-border/30 bg-card/70 p-3 shadow-soft">
      <div className="flex min-w-0 items-start gap-3">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-success/10 text-success">
          {item.installed ? <Check className="h-4 w-4" /> : <Download className="h-4 w-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-medium text-foreground">{item.name}</h3>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {item.description || "Marketplace skill"}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
            <span className="rounded-full bg-background/60 px-1.5 py-0.5 font-mono">{item.slash_name}</span>
            {item.allowed_tools.slice(0, 2).map((tool) => (
              <span key={tool} className="rounded-full bg-background/60 px-1.5 py-0.5">
                {tool}
              </span>
            ))}
          </div>
        </div>
        <Button
          variant={item.installed ? "secondary" : "outline"}
          size="xs"
          disabled={item.installed || pending}
          onClick={onInstall}
          className="shrink-0 rounded-xl"
        >
          {pending ? <Loader2 className="h-3 w-3 animate-spin" /> : item.installed ? <Check className="h-3 w-3" /> : <Download className="h-3 w-3" />}
          <span>{item.installed ? "Installed" : "Install"}</span>
        </Button>
      </div>
    </article>
  );
}

function SkillDetailDialog({
  invocationName,
  open,
  onOpenChange,
  baseUrl,
  workspaceRoot,
}: {
  invocationName?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  baseUrl: string;
  workspaceRoot?: string | null;
}) {
  const detail = useQuery({
    queryKey: ["skill-detail", baseUrl, workspaceRoot, invocationName],
    queryFn: () => getSkillDetail(baseUrl, invocationName ?? "", workspaceRoot),
    enabled: open && Boolean(invocationName),
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-background/55 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 flex max-h-[min(760px,calc(100vh-40px))] w-[min(760px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-glass-border/35 bg-popover/98 shadow-floating">
          <div className="flex shrink-0 items-center gap-3 border-b border-glass-border/25 px-4 py-3">
            <div className="min-w-0 flex-1">
              <Dialog.Title className="truncate text-sm font-semibold text-foreground">
                {detail.data?.name ?? "Skill"}
              </Dialog.Title>
              <Dialog.Description className="mt-1 truncate text-xs text-muted-foreground">
                {detail.data?.slash_name ?? invocationName}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="iconSm" aria-label="Close skill detail">
                <X className="h-3.5 w-3.5" />
              </Button>
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {detail.isLoading ? <LoadingRow label="Loading skill detail" /> : null}
            {detail.isError ? <ErrorRow label="Skill detail unavailable" /> : null}
            {detail.data ? (
              <div className="space-y-4">
                <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
                  <MetaLine label="Source" value={sourceLabel(detail.data.source)} />
                  <MetaLine label="Status" value={detail.data.enabled ? "Active" : "Inactive"} />
                  <MetaLine label="Path" value={detail.data.path} mono />
                  <MetaLine label="Tools" value={detail.data.allowed_tools.join(", ") || "None"} />
                </div>
                {detail.data.when_to_use ? (
                  <div className="rounded-xl border border-glass-border/30 bg-card/70 p-3 text-xs leading-5 text-muted-foreground">
                    {detail.data.when_to_use}
                  </div>
                ) : null}
                <div className="prose prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-li:text-muted-foreground prose-pre:border prose-pre:border-glass-border/35 prose-pre:bg-background/80 prose-code:text-foreground">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.data.content || "_No skill body._"}</ReactMarkdown>
                </div>
              </div>
            ) : null}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function MetaLine({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0 rounded-xl border border-glass-border/25 bg-background/45 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/75">{label}</div>
      <div className={["mt-1 truncate text-foreground", mono ? "font-mono text-[11px]" : ""].join(" ")} title={value}>
        {value}
      </div>
    </div>
  );
}

function LoadingRow({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-glass-border/25 bg-card/50 px-3 py-3 text-xs text-muted-foreground">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      <span>{label}</span>
    </div>
  );
}

function ErrorRow({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-3 py-3 text-xs text-destructive">
      {label}
    </div>
  );
}

function EmptyRow({ label }: { label: string }) {
  return (
    <div className="rounded-xl border border-glass-border/25 bg-card/50 px-3 py-3 text-xs text-muted-foreground">
      {label}
    </div>
  );
}

function filterSkills(skills: SkillSummary[], query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) return skills;
  return skills.filter((skill) =>
    [skill.name, skill.invocation_name, skill.description, skill.source, skill.slash_name]
      .some((value) => String(value ?? "").toLowerCase().includes(needle)),
  );
}

function filterMarketplace(items: SkillMarketplaceItem[], query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) return items;
  return items.filter((item) =>
    [item.name, item.invocation_name, item.description, item.slash_name]
      .some((value) => String(value ?? "").toLowerCase().includes(needle)),
  );
}

function sourceLabel(source: string) {
  if (source === "codex") return "Codex";
  if (source === "personagent") return "PersonAgent";
  if (source === "workspace") return "Workspace";
  if (source === "configured") return "Configured";
  return "Local";
}
