import type { ChatSet, ChatGet, ComposerAnnotation } from "./internal";

export const createComposerSlice = (set: ChatSet, _get: ChatGet) => ({
  composerAnnotations: [] as ComposerAnnotation[],
  composerPlanMode: false,

  addComposerAnnotation: (annotation: ComposerAnnotation) =>
    set((state) => ({
      composerAnnotations: [
        ...state.composerAnnotations.filter((item) => item.id !== annotation.id),
        annotation,
      ],
    })),

  removeComposerAnnotation: (id: number) =>
    set((state) => ({
      composerAnnotations: state.composerAnnotations.filter(
        (annotation) => annotation.id !== id,
      ),
    })),

  clearComposerAnnotations: () => set({ composerAnnotations: [] }),

  setComposerPlanMode: (active: boolean) => set({ composerPlanMode: active }),
});
