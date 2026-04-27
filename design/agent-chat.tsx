import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Bot,
  Brain,
  ChevronDown,
  ChevronRight,
  FileText,
  Search,
  Send,
  Sparkles,
  User,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

const reasoningSteps = [
  "Analisando o pedido e separando estados visuais do fluxo de agentes.",
  "Preparando indicador principal com brilho contínuo durante execução.",
  "Sincronizando ferramentas Read com contagem incremental de arquivos.",
  "Agrupando Find, Grep e Glob como operações de busca com auto-colapso.",
  "Finalizando resposta e preservando o histórico colapsável no chat.",
];

const finalAnswer =
  "Implementei uma Chat UI premium com fluxo de Reasoning streamado, spinner principal Thinking..., estados de ferramentas com Reading N Files... e Searching..., além de auto-colapso ao finalizar cada etapa.";

function cn(...classes) {
  return classes.filter(Boolean).join(" ");
}

function ShimmerText({ children, className = "" }) {
  return (
    <span
      className={cn(
        "relative inline-flex overflow-hidden bg-gradient-to-r from-zinc-500 via-zinc-950 to-zinc-500 bg-[length:220%_100%] bg-clip-text text-transparent animate-[shimmer_1.8s_linear_infinite] dark:from-zinc-500 dark:via-white dark:to-zinc-500",
        className
      )}
    >
      {children}
    </span>
  );
}

function PremiumSpinner({ size = "sm" }) {
  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 rounded-full border border-zinc-300 border-t-zinc-950 dark:border-zinc-700 dark:border-t-white animate-spin",
        size === "lg" ? "h-5 w-5" : "h-4 w-4"
      )}
    />
  );
}

function AgentStatus({ active, label = "Thinking..." }) {
  return (
    <AnimatePresence>
      {active && (
        <motion.div
          initial={{ opacity: 0, y: -8, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.98 }}
          transition={{ duration: 0.22 }}
          className="sticky top-0 z-20 border-b border-zinc-200/70 bg-white/75 px-4 py-3 backdrop-blur-xl dark:border-zinc-800/80 dark:bg-zinc-950/70"
        >
          <div className="mx-auto flex max-w-4xl items-center justify-between rounded-2xl border border-zinc-200/80 bg-white/80 px-4 py-3 shadow-sm shadow-zinc-950/5 dark:border-zinc-800 dark:bg-zinc-900/70">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-950 text-white shadow-sm dark:bg-white dark:text-zinc-950">
                <PremiumSpinner size="lg" />
              </div>
              <div>
                <div className="text-sm font-semibold tracking-tight text-zinc-950 dark:text-white">
                  <ShimmerText>{label}</ShimmerText>
                </div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  Os agentes estão executando em tempo real
                </p>
              </div>
            </div>
            <Badge variant="secondary" className="rounded-full bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              Live
            </Badge>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function CollapsibleProcess({
  icon: Icon,
  title,
  activeLabel,
  collapsedLabel,
  active,
  completed,
  children,
  defaultOpen = true,
}) {
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    if (active) setOpen(true);
  }, [active]);

  useEffect(() => {
    if (completed && !active) {
      const timer = window.setTimeout(() => setOpen(false), 650);
      return () => window.clearTimeout(timer);
    }
  }, [completed, active]);

  return (
    <motion.div layout className="overflow-hidden rounded-2xl border border-zinc-200 bg-zinc-50/70 shadow-sm shadow-zinc-950/[0.03] dark:border-zinc-800 dark:bg-zinc-900/60">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-zinc-100/70 dark:hover:bg-zinc-800/60"
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-white text-zinc-700 shadow-sm ring-1 ring-zinc-200 dark:bg-zinc-950 dark:text-zinc-200 dark:ring-zinc-800">
            {active ? <PremiumSpinner /> : <Icon className="h-4 w-4" />}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium text-zinc-950 dark:text-white">
              {active ? <ShimmerText>{activeLabel}</ShimmerText> : <span>{completed ? collapsedLabel : title}</span>}
            </div>
            {!open && completed && (
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">Clique para ver o processo</p>
            )}
          </div>
        </div>
        {open ? <ChevronDown className="h-4 w-4 text-zinc-400" /> : <ChevronRight className="h-4 w-4 text-zinc-400" />}
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
          >
            <div className="border-t border-zinc-200 px-4 py-3 text-sm leading-6 text-zinc-600 dark:border-zinc-800 dark:text-zinc-300">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function ReasoningBlock({ steps, active, completed }) {
  return (
    <CollapsibleProcess
      icon={Brain}
      title="Reasoning"
      activeLabel="Reasoning..."
      collapsedLabel="Reasoning"
      active={active}
      completed={completed}
    >
      <div className="space-y-2">
        {steps.map((step, index) => (
          <motion.div
            key={`${step}-${index}`}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex gap-3"
          >
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-zinc-400 dark:bg-zinc-500" />
            <span>{step}</span>
          </motion.div>
        ))}
        {active && (
          <div className="flex items-center gap-2 pt-1 text-xs text-zinc-500">
            <PremiumSpinner /> Streamando processo em tempo real
          </div>
        )}
      </div>
    </CollapsibleProcess>
  );
}

function ToolBlock({ type, count, active, completed, logs }) {
  const isRead = type === "read";
  const Icon = isRead ? FileText : Search;
  const activeLabel = isRead ? `Reading ${count} ${count === 1 ? "File" : "Files"}...` : "Searching...";
  const collapsedLabel = isRead ? `Reading ${count} ${count === 1 ? "File" : "Files"}` : "Searching";

  return (
    <CollapsibleProcess
      icon={Icon}
      title={isRead ? "Read" : "Find / Grep / Glob"}
      activeLabel={activeLabel}
      collapsedLabel={collapsedLabel}
      active={active}
      completed={completed}
    >
      <div className="space-y-2">
        {logs.map((log, index) => (
          <motion.div
            key={`${log}-${index}`}
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 text-xs text-zinc-600 ring-1 ring-zinc-200 dark:bg-zinc-950/80 dark:text-zinc-300 dark:ring-zinc-800"
          >
            <Icon className="h-3.5 w-3.5 text-zinc-400" />
            <span>{log}</span>
          </motion.div>
        ))}
        {active && (
          <div className="flex items-center gap-2 pt-1 text-xs text-zinc-500">
            <PremiumSpinner /> {activeLabel}
          </div>
        )}
      </div>
    </CollapsibleProcess>
  );
}

function MessageBubble({ role, children }) {
  const isUser = role === "user";

  return (
    <div className={cn("flex gap-3", isUser ? "justify-end" : "justify-start")}>
      {!isUser && (
        <div className="mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-zinc-950 text-white shadow-sm dark:bg-white dark:text-zinc-950">
          <Bot className="h-4 w-4" />
        </div>
      )}
      <div
        className={cn(
          "max-w-[78%] rounded-3xl px-4 py-3 text-sm leading-6 shadow-sm",
          isUser
            ? "bg-zinc-950 text-white dark:bg-white dark:text-zinc-950"
            : "border border-zinc-200 bg-white text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100"
        )}
      >
        {children}
      </div>
      {isUser && (
        <div className="mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border border-zinc-200 bg-white text-zinc-700 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
          <User className="h-4 w-4" />
        </div>
      )}
    </div>
  );
}

function useMockAgentRun() {
  const [running, setRunning] = useState(false);
  const [phase, setPhase] = useState("idle");
  const [reasoning, setReasoning] = useState([]);
  const [readCount, setReadCount] = useState(0);
  const [readLogs, setReadLogs] = useState([]);
  const [searchLogs, setSearchLogs] = useState([]);
  const [answer, setAnswer] = useState("");
  const timers = useRef([]);

  const clearTimers = () => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current = [];
  };

  const schedule = (callback, delay) => {
    const timer = window.setTimeout(callback, delay);
    timers.current.push(timer);
  };

  useEffect(() => () => clearTimers(), []);

  const run = () => {
    clearTimers();
    setRunning(true);
    setPhase("reasoning");
    setReasoning([]);
    setReadCount(0);
    setReadLogs([]);
    setSearchLogs([]);
    setAnswer("");

    reasoningSteps.forEach((step, index) => {
      schedule(() => setReasoning((items) => [...items, step]), 500 + index * 650);
    });

    schedule(() => {
      setPhase("read");
      setReadCount(1);
      setReadLogs(["Lendo src/app/chat/page.tsx"]);
    }, 4200);

    schedule(() => {
      setReadCount(2);
      setReadLogs((items) => [...items, "Lendo src/components/agent-tools.tsx"]);
    }, 5100);

    schedule(() => {
      setReadCount(3);
      setReadLogs((items) => [...items, "Lendo src/components/reasoning-panel.tsx"]);
    }, 5900);

    schedule(() => {
      setPhase("search");
      setSearchLogs(["Find: componentes de ferramenta"]);
    }, 7100);

    schedule(() => {
      setSearchLogs((items) => [...items, "Grep: estados de execution / tool_call"]);
    }, 7900);

    schedule(() => {
      setSearchLogs((items) => [...items, "Glob: **/*chat*.tsx"]);
    }, 8600);

    schedule(() => {
      setPhase("answer");
      let current = "";
      finalAnswer.split(" ").forEach((word, index) => {
        schedule(() => {
          current = `${current}${index === 0 ? "" : " "}${word}`;
          setAnswer(current);
        }, index * 80);
      });
    }, 9600);

    schedule(() => {
      setRunning(false);
      setPhase("done");
    }, 12500);
  };

  return {
    running,
    phase,
    reasoning,
    readCount,
    readLogs,
    searchLogs,
    answer,
    run,
  };
}

export default function PremiumChatUI() {
  const { running, phase, reasoning, readCount, readLogs, searchLogs, answer, run } = useMockAgentRun();
  const [input, setInput] = useState("Crie uma UI moderna para Chat com Reasoning e ferramentas colapsáveis");

  const statusLabel = useMemo(() => {
    if (phase === "read") return `Reading ${readCount} ${readCount === 1 ? "File" : "Files"}...`;
    if (phase === "search") return "Searching...";
    if (phase === "reasoning") return "Thinking...";
    if (phase === "answer") return "Thinking...";
    return "Thinking...";
  }, [phase, readCount]);

  const hasStarted = phase !== "idle";
  const reasoningCompleted = ["read", "search", "answer", "done"].includes(phase);
  const readCompleted = ["search", "answer", "done"].includes(phase);
  const searchCompleted = ["answer", "done"].includes(phase);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(113,113,122,0.16),_transparent_36%),linear-gradient(to_bottom,_#ffffff,_#f4f4f5)] text-zinc-950 dark:bg-[radial-gradient(circle_at_top,_rgba(244,244,245,0.10),_transparent_36%),linear-gradient(to_bottom,_#09090b,_#18181b)] dark:text-white">
      <style>{`
        @keyframes shimmer {
          0% { background-position: 220% 0; }
          100% { background-position: -220% 0; }
        }
      `}</style>

      <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-4 py-6">
        <header className="mb-5 flex items-center justify-between rounded-3xl border border-zinc-200/80 bg-white/70 px-5 py-4 shadow-sm shadow-zinc-950/5 backdrop-blur-xl dark:border-zinc-800 dark:bg-zinc-950/55">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-zinc-950 text-white shadow-sm dark:bg-white dark:text-zinc-950">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-base font-semibold tracking-tight">Premium Agent Chat</h1>
              <p className="text-sm text-zinc-500 dark:text-zinc-400">Reasoning, ferramentas e execução em tempo real</p>
            </div>
          </div>
          <Badge className="rounded-full bg-zinc-950 px-3 py-1 text-white hover:bg-zinc-950 dark:bg-white dark:text-zinc-950">
            shadcn style
          </Badge>
        </header>

        <Card className="flex min-h-[760px] flex-1 overflow-hidden rounded-[2rem] border-zinc-200/80 bg-white/72 shadow-2xl shadow-zinc-950/[0.06] backdrop-blur-xl dark:border-zinc-800 dark:bg-zinc-950/58 dark:shadow-black/20">
          <CardContent className="flex w-full flex-col p-0">
            <AgentStatus active={running} label={statusLabel} />

            <ScrollArea className="flex-1">
              <main className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-6">
                <MessageBubble role="user">
                  Quero uma Chat UI moderna, premium, com Reasoning streamado, auto-colapso e estados visuais para ferramentas Read, Find, Grep e Glob.
                </MessageBubble>

                <div className="flex gap-3">
                  <div className="mt-1 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-zinc-950 text-white shadow-sm dark:bg-white dark:text-zinc-950">
                    <Bot className="h-4 w-4" />
                  </div>

                  <div className="w-full max-w-[82%] space-y-3">
                    {!hasStarted && (
                      <div className="rounded-3xl border border-zinc-200 bg-white px-4 py-4 text-sm text-zinc-600 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
                        Clique em <span className="font-medium text-zinc-950 dark:text-white">Run demo</span> para ver o fluxo completo: Thinking, Reasoning, Reading, Searching e resposta final.
                      </div>
                    )}

                    {hasStarted && (
                      <ReasoningBlock
                        steps={reasoning}
                        active={phase === "reasoning"}
                        completed={reasoningCompleted}
                      />
                    )}

                    {(readLogs.length > 0 || readCompleted) && (
                      <ToolBlock
                        type="read"
                        count={Math.max(readCount, readLogs.length)}
                        active={phase === "read"}
                        completed={readCompleted}
                        logs={readLogs}
                      />
                    )}

                    {(searchLogs.length > 0 || searchCompleted) && (
                      <ToolBlock
                        type="search"
                        count={0}
                        active={phase === "search"}
                        completed={searchCompleted}
                        logs={searchLogs}
                      />
                    )}

                    {(answer || phase === "answer" || phase === "done") && (
                      <motion.div
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="rounded-3xl border border-zinc-200 bg-white px-4 py-4 text-sm leading-6 text-zinc-800 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100"
                      >
                        {answer}
                        {phase === "answer" && <span className="ml-1 inline-block h-4 w-1 translate-y-0.5 animate-pulse rounded-full bg-zinc-900 dark:bg-white" />}
                      </motion.div>
                    )}
                  </div>
                </div>
              </main>
            </ScrollArea>

            <footer className="border-t border-zinc-200/80 bg-white/80 p-4 backdrop-blur-xl dark:border-zinc-800 dark:bg-zinc-950/70">
              <div className="mx-auto flex max-w-4xl items-end gap-3 rounded-3xl border border-zinc-200 bg-zinc-50 p-2 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/80">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white text-zinc-500 ring-1 ring-zinc-200 dark:bg-zinc-950 dark:ring-zinc-800">
                  <Wrench className="h-4 w-4" />
                </div>
                <Input
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  className="min-h-10 border-0 bg-transparent px-0 text-sm shadow-none focus-visible:ring-0"
                  placeholder="Digite uma mensagem..."
                />
                <Button
                  onClick={run}
                  disabled={running}
                  className="h-10 rounded-2xl bg-zinc-950 px-4 text-white shadow-sm hover:bg-zinc-800 disabled:opacity-70 dark:bg-white dark:text-zinc-950 dark:hover:bg-zinc-200"
                >
                  {running ? <PremiumSpinner /> : <Send className="h-4 w-4" />}
                  <span className="ml-2 hidden sm:inline">{running ? "Running" : "Run demo"}</span>
                </Button>
              </div>
            </footer>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
