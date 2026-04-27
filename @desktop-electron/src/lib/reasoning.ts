export interface ThinkingTagState {
  insideThink: boolean;
  pending: string;
  activeEndTag: string;
}

const thinkTags = [
  ["<think>", "</think>"],
  ["<thinking>", "</thinking>"],
  ["<reasoning>", "</reasoning>"],
] as const;

export function createThinkingTagState(): ThinkingTagState {
  return {
    insideThink: false,
    pending: "",
    activeEndTag: "</think>",
  };
}

export function splitThinkingTags(
  text: string,
  state: ThinkingTagState = createThinkingTagState(),
  flush = false,
) {
  if (!text && !flush) return { content: "", reasoning: "" };

  let buffer = `${state.pending}${text}`;
  state.pending = "";
  const contentParts: string[] = [];
  const reasoningParts: string[] = [];

  while (buffer.length > 0) {
    if (state.insideThink) {
      const index = findCaseInsensitive(buffer, state.activeEndTag);
      if (index >= 0) {
        reasoningParts.push(buffer.slice(0, index));
        buffer = buffer.slice(index + state.activeEndTag.length);
        state.insideThink = false;
        state.activeEndTag = "</think>";
        continue;
      }

      const split = splitPossibleSuffix(buffer, state.activeEndTag);
      reasoningParts.push(split.safe);
      state.pending = split.pending;
      break;
    }

    const start = findFirstStartTag(buffer);
    const end = findFirstEndTag(buffer);
    if (end && (!start || end.index < start.index)) {
      reasoningParts.push(buffer.slice(0, end.index));
      buffer = buffer.slice(end.index + end.endTag.length);
      state.insideThink = false;
      state.activeEndTag = "</think>";
      continue;
    }

    if (start) {
      contentParts.push(buffer.slice(0, start.index));
      buffer = buffer.slice(start.index + start.startTag.length);
      state.insideThink = true;
      state.activeEndTag = start.endTag;
      continue;
    }

    const split = splitPossibleSuffixes(
      buffer,
      thinkTags.map(([startTag]) => startTag),
    );
    contentParts.push(split.safe);
    state.pending = split.pending;
    break;
  }

  if (flush && state.pending) {
    if (state.insideThink) {
      reasoningParts.push(state.pending);
    } else {
      contentParts.push(state.pending);
    }
    state.pending = "";
  }

  return {
    content: contentParts.join(""),
    reasoning: reasoningParts.join(""),
  };
}

export function splitCompleteThinkingText(text: string) {
  const state = createThinkingTagState();
  return splitThinkingTags(text, state, true);
}

function findFirstStartTag(text: string) {
  const matches = thinkTags
    .map(([startTag, endTag]) => ({
      index: findCaseInsensitive(text, startTag),
      startTag,
      endTag,
    }))
    .filter((match) => match.index >= 0);
  return matches.length ? matches.sort((left, right) => left.index - right.index)[0] : undefined;
}

function findFirstEndTag(text: string) {
  const matches = thinkTags
    .map(([, endTag]) => ({
      index: findCaseInsensitive(text, endTag),
      endTag,
    }))
    .filter((match) => match.index >= 0);
  return matches.length ? matches.sort((left, right) => left.index - right.index)[0] : undefined;
}

function findCaseInsensitive(text: string, pattern: string) {
  return text.toLowerCase().indexOf(pattern);
}

function splitPossibleSuffixes(text: string, patterns: readonly string[]) {
  return patterns
    .map((pattern) => splitPossibleSuffix(text, pattern))
    .sort((left, right) => left.safe.length - right.safe.length)[0];
}

function splitPossibleSuffix(text: string, pattern: string) {
  const maxSuffix = Math.min(text.length, pattern.length - 1);
  const lowered = text.toLowerCase();
  for (let length = maxSuffix; length > 0; length -= 1) {
    const suffix = lowered.slice(-length);
    if (pattern.startsWith(suffix)) {
      return {
        safe: text.slice(0, -length),
        pending: text.slice(-length),
      };
    }
  }
  return { safe: text, pending: "" };
}
