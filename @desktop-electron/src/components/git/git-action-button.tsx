import { useState } from "react";
import { GitBranch, GitCommit, GitPullRequest, Loader2, Upload, FolderX, GitBranchIcon } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { useGitStatus, useGitCommit, useGitPush, useGitOpenPr } from "../../stores/git-store";
import { useAppStore } from "../../stores/app-store";

export function GitActionButton() {
  const workspaceRoot = useAppStore((state) => state.selectedWorkspace);
  const [open, setOpen] = useState(false);
  const [commitDialogOpen, setCommitDialogOpen] = useState(false);
  const [commitMessage, setCommitMessage] = useState("");

  const { data: status, isLoading, isFetching } = useGitStatus(true);
  const commitMutation = useGitCommit();
  const pushMutation = useGitPush();
  const prMutation = useGitOpenPr();

  // Estados derivados
  const hasWorkspace = Boolean(workspaceRoot);
  const hasRepo = hasWorkspace && Boolean(status?.branch);
  const isDirty = status?.is_dirty ?? false;
  const hasAhead = (status?.ahead ?? 0) > 0;
  const hasBehind = (status?.behind ?? 0) > 0;
  const modifiedCount = status?.modified_count ?? 0;
  const untrackedCount = status?.untracked_count ?? 0;
  const branch = status?.branch || "";

  // Classes base do botão pill
  const baseButtonClass =
    "inline-flex h-7 items-center gap-1.5 rounded-full px-3 text-[11px] font-medium transition-all duration-200 border";

  let buttonClass = baseButtonClass;
  let showPulse = false;

  if (!hasWorkspace) {
    // Sem workspace selecionado
    buttonClass += " border-glass-border/25 bg-transparent text-muted-foreground/50 cursor-not-allowed";
  } else if (isLoading) {
    // Carregando status do workspace
    buttonClass += " border-glass-border/35 bg-background/80 text-muted-foreground";
  } else if (!hasRepo) {
    // Tem workspace mas não é repo git
    buttonClass += " border-glass-border/25 bg-transparent text-muted-foreground/60";
  } else if (isDirty && hasAhead) {
    buttonClass += " border-warning/30 bg-warning/10 text-warning";
    showPulse = true;
  } else if (isDirty) {
    buttonClass += " border-warning/30 bg-warning/10 text-warning";
    showPulse = true;
  } else if (hasAhead) {
    buttonClass += " border-primary/30 bg-primary/10 text-primary";
  } else if (hasBehind) {
    buttonClass += " border-glass-border/35 bg-background/80 text-muted-foreground";
  } else {
    buttonClass += " border-glass-border/35 bg-background/80 text-muted-foreground";
  }

  const handleCommit = async () => {
    if (!commitMessage.trim()) return;
    await commitMutation.mutateAsync(commitMessage.trim());
    setCommitMessage("");
    setCommitDialogOpen(false);
  };

  const buttonContent = (
    <>
      {!hasWorkspace ? (
        <FolderX className="h-3 w-3 shrink-0" />
      ) : !hasRepo && !isLoading ? (
        <GitBranchIcon className="h-3 w-3 shrink-0 opacity-50" />
      ) : (
        <GitBranch className="h-3 w-3 shrink-0" />
      )}

      {!hasWorkspace ? (
        <span>Sem workspace</span>
      ) : isLoading ? (
        <span className="flex items-center gap-1">
          <Loader2 className="h-2.5 w-2.5 animate-spin" />
          <span className="text-muted-foreground">Git</span>
        </span>
      ) : !hasRepo ? (
        <span>Sem repositório</span>
      ) : (
        <span className="truncate">{branch}</span>
      )}

      {/* Indicador de atualização em background */}
      {hasRepo && isFetching && !isLoading && (
        <Loader2 className="h-2.5 w-2.5 animate-spin text-muted-foreground/60" />
      )}

      {/* Indicador de alterações não commitadas */}
      {hasRepo && isDirty && (
        <span className="relative flex h-3.5 items-center justify-center">
          <span
            className={[
              "absolute inline-flex h-2 w-2 rounded-full bg-warning",
              showPulse ? "personagent-git-pulse" : "",
            ].join(" ")}
          />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-warning" />
        </span>
      )}

      {/* Badge de commits ahead */}
      {hasRepo && hasAhead && !isDirty && status && (
        <span className="rounded-full bg-primary/20 px-1 text-[10px] font-semibold text-primary">
          ↑{status.ahead}
        </span>
      )}

      {/* Badge de arquivos modificados */}
      {hasRepo && isDirty && modifiedCount > 0 && (
        <span className="rounded-full bg-warning/20 px-1 text-[10px] font-semibold text-warning">
          {modifiedCount}
        </span>
      )}
    </>
  );

  return (
    <>
      <DropdownMenu open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className={buttonClass}
            disabled={!hasWorkspace}
            title={
              !hasWorkspace
                ? "Selecione um workspace"
                : !hasRepo
                  ? "Nenhum repositório Git detectado"
                  : `${branch} — clique para ações`
            }
          >
            {buttonContent}
          </button>
        </DropdownMenuTrigger>

        <DropdownMenuContent
          side="bottom"
          align="end"
          className="personagent-dropdown-fade w-64"
        >
          <DropdownMenuLabel className="text-xs font-semibold">
            Git Actions
          </DropdownMenuLabel>

          {/* Status summary */}
          <div className="space-y-1.5 px-2 py-2 text-[11px] text-muted-foreground">
            {!hasWorkspace ? (
              <div className="flex items-center gap-2 text-muted-foreground/70">
                <FolderX className="h-3 w-3 shrink-0" />
                <span>Nenhum workspace selecionado</span>
              </div>
            ) : isLoading ? (
              <div className="flex items-center gap-2">
                <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
                <span>Carregando status...</span>
              </div>
            ) : !hasRepo ? (
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <GitBranchIcon className="h-3 w-3 shrink-0 opacity-50" />
                  <span className="font-medium text-foreground">Sem repositório Git</span>
                </div>
                <p className="pl-5 text-[10px] leading-4 text-muted-foreground/70">
                  Este diretório não é um repositório Git. Inicie um com "git init" ou selecione outro workspace.
                </p>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <GitBranch className="h-3 w-3 shrink-0" />
                  <span className="font-medium text-foreground">{branch}</span>
                </div>
                {(modifiedCount > 0 || untrackedCount > 0) && (
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />
                    <span>
                      {modifiedCount} modificado{modifiedCount !== 1 ? "s" : ""}
                      {untrackedCount > 0
                        ? `, ${untrackedCount} não rastreado${untrackedCount !== 1 ? "s" : ""}`
                        : ""}
                    </span>
                  </div>
                )}
                {hasAhead && status && (
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                    <span>{status.ahead} commit(s) à frente do remote</span>
                  </div>
                )}
                {hasBehind && status && (
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground" />
                    <span>{status.behind} commit(s) atrás do remote</span>
                  </div>
                )}
                {!isDirty && !hasAhead && !hasBehind && (
                  <div className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-success" />
                    <span>Working tree limpo</span>
                  </div>
                )}
              </>
            )}
          </div>

          <DropdownMenuSeparator />

          <DropdownMenuItem
            onSelect={(e) => {
              e.preventDefault();
              if (!hasRepo) return;
              setOpen(false);
              setCommitDialogOpen(true);
            }}
            disabled={!hasRepo || !isDirty || commitMutation.isPending}
            className="gap-2 text-xs"
          >
            <GitCommit className="h-3.5 w-3.5" />
            Commit alterações...
            {commitMutation.isPending && <Loader2 className="ml-auto h-3 w-3 animate-spin" />}
          </DropdownMenuItem>

          <DropdownMenuItem
            onSelect={(e) => {
              e.preventDefault();
              if (!hasRepo) return;
              void pushMutation.mutateAsync();
            }}
            disabled={!hasRepo || !hasAhead || pushMutation.isPending}
            className="gap-2 text-xs"
          >
            <Upload className="h-3.5 w-3.5" />
            Fazer Push
            {pushMutation.isPending && <Loader2 className="ml-auto h-3 w-3 animate-spin" />}
          </DropdownMenuItem>

          <DropdownMenuItem
            onSelect={(e) => {
              e.preventDefault();
              if (!hasRepo) return;
              void prMutation.mutateAsync();
            }}
            disabled={!hasRepo || !hasAhead || prMutation.isPending}
            className="gap-2 text-xs"
          >
            <GitPullRequest className="h-3.5 w-3.5" />
            Abrir PR
            {prMutation.isPending && <Loader2 className="ml-auto h-3 w-3 animate-spin" />}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Commit Dialog Overlay */}
      {commitDialogOpen && hasRepo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-glass-border/35 bg-card/95 p-4 shadow-floating backdrop-blur-xl">
            <h3 className="text-sm font-semibold text-foreground">Commit alterações</h3>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {modifiedCount} arquivo(s) modificado(s) serão commitados.
            </p>
            <textarea
              value={commitMessage}
              onChange={(e) => setCommitMessage(e.target.value)}
              placeholder="Mensagem do commit..."
              className="mt-3 min-h-[80px] w-full resize-none rounded-xl border border-glass-border/35 bg-background/60 px-3 py-2 text-xs text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/30 focus:ring-1 focus:ring-primary/20"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  void handleCommit();
                }
              }}
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setCommitDialogOpen(false);
                  setCommitMessage("");
                }}
                className="rounded-lg px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-glass/60 hover:text-foreground"
              >
                Cancelar
              </button>
              <button
                type="button"
                disabled={!commitMessage.trim() || commitMutation.isPending}
                onClick={() => void handleCommit()}
                className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-40"
              >
                {commitMutation.isPending ? "Commitando..." : "Commit"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
