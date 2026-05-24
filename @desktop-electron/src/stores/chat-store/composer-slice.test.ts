import { describe, it, expect, vi } from "vitest";
import { createComposerSlice } from "./composer-slice";
import type { ComposerAnnotation, ChatState } from "./internal";

function makeAnnotation(overrides: Partial<ComposerAnnotation> = {}): ComposerAnnotation {
  return {
    id: 1,
    fileName: "test.ts",
    filePath: "/src/test.ts",
    displayPath: "src/test.ts",
    startLine: 1,
    endLine: 10,
    text: "some code",
    selectedLines: "line 1\nline 2",
    language: "typescript",
    ...overrides,
  };
}

function createTestSlice() {
  let state: Record<string, unknown> = {};
  const set = vi.fn((partial: Partial<ChatState> | ((s: ChatState) => Partial<ChatState>)) => {
    if (typeof partial === "function") {
      Object.assign(state, partial(state as unknown as ChatState));
    } else {
      Object.assign(state, partial);
    }
  });
  const get = vi.fn(() => state as unknown as ChatState);
  const slice = createComposerSlice(set, get);
  Object.assign(state, slice);
  return { state, set, get, slice };
}

describe("createComposerSlice", () => {
  it("initializes with empty annotations and planMode false", () => {
    const { slice } = createTestSlice();
    expect(slice.composerAnnotations).toEqual([]);
    expect(slice.composerPlanMode).toBe(false);
  });

  it("addComposerAnnotation appends a new annotation", () => {
    const { state, slice } = createTestSlice();
    const annotation = makeAnnotation({ id: 1 });
    slice.addComposerAnnotation(annotation);
    expect((state as any).composerAnnotations).toHaveLength(1);
    expect((state as any).composerAnnotations[0].id).toBe(1);
  });

  it("addComposerAnnotation replaces annotation with same id", () => {
    const { state, slice } = createTestSlice();
    const a1 = makeAnnotation({ id: 1, text: "first" });
    const a2 = makeAnnotation({ id: 1, text: "second" });
    slice.addComposerAnnotation(a1);
    slice.addComposerAnnotation(a2);
    expect((state as any).composerAnnotations).toHaveLength(1);
    expect((state as any).composerAnnotations[0].text).toBe("second");
  });

  it("addComposerAnnotation keeps different ids", () => {
    const { state, slice } = createTestSlice();
    slice.addComposerAnnotation(makeAnnotation({ id: 1 }));
    slice.addComposerAnnotation(makeAnnotation({ id: 2 }));
    expect((state as any).composerAnnotations).toHaveLength(2);
  });

  it("removeComposerAnnotation removes by id", () => {
    const { state, slice } = createTestSlice();
    slice.addComposerAnnotation(makeAnnotation({ id: 1 }));
    slice.addComposerAnnotation(makeAnnotation({ id: 2 }));
    slice.removeComposerAnnotation(1);
    expect((state as any).composerAnnotations).toHaveLength(1);
    expect((state as any).composerAnnotations[0].id).toBe(2);
  });

  it("removeComposerAnnotation is no-op for non-existent id", () => {
    const { state, slice } = createTestSlice();
    slice.addComposerAnnotation(makeAnnotation({ id: 1 }));
    slice.removeComposerAnnotation(999);
    expect((state as any).composerAnnotations).toHaveLength(1);
  });

  it("clearComposerAnnotations removes all", () => {
    const { state, slice } = createTestSlice();
    slice.addComposerAnnotation(makeAnnotation({ id: 1 }));
    slice.addComposerAnnotation(makeAnnotation({ id: 2 }));
    slice.clearComposerAnnotations();
    expect((state as any).composerAnnotations).toEqual([]);
  });

  it("setComposerPlanMode toggles plan mode", () => {
    const { state, slice } = createTestSlice();
    slice.setComposerPlanMode(true);
    expect((state as any).composerPlanMode).toBe(true);
    slice.setComposerPlanMode(false);
    expect((state as any).composerPlanMode).toBe(false);
  });
});
