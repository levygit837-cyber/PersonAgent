export function parseSsePayloads(buffer: string) {
  const payloads: unknown[] = [];
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  const rest = blocks.pop() ?? "";

  for (const block of blocks) {
    const dataLines = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart());
    if (dataLines.length === 0) continue;
    const data = dataLines.join("\n").trim();
    if (!data) continue;
    if (data === "[DONE]") {
      payloads.push({ __done: true });
      continue;
    }
    payloads.push(JSON.parse(data));
  }

  return { payloads, rest };
}

export async function* readSseStream<T>(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<T, void, unknown> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = String(body.detail ?? detail);
    } catch {
      // Keep status text when the response body is not JSON.
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }

  if (!response.body) {
    throw new Error("Streaming response did not include a readable body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) return;
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSsePayloads(buffer);
      buffer = parsed.rest;
      for (const payload of parsed.payloads) {
        if ((payload as { __done?: boolean }).__done) return;
        yield payload as T;
      }
    }

    buffer += decoder.decode();
    const parsed = parseSsePayloads(`${buffer}\n\n`);
    for (const payload of parsed.payloads) {
      if ((payload as { __done?: boolean }).__done) return;
      yield payload as T;
    }
  } finally {
    reader.releaseLock();
  }
}
