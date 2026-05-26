export type OperationFeedback = {
  kind: "success" | "error";
  title: string;
  detail?: string;
};
