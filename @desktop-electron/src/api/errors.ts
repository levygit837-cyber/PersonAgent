export interface ApiErrorEnvelope {
  code: string;
  category: string;
  severity?: string;
  message: string;
  status: number;
  retryable: boolean;
  correlation_id?: string;
  safe_for_model?: boolean;
  safe_for_telemetry?: boolean;
  metadata?: Record<string, unknown>;
}

export class PersonAgentApiError extends Error {
  envelope: ApiErrorEnvelope;
  status: number;
  retryable: boolean;

  constructor(envelope: ApiErrorEnvelope) {
    super(envelope.message || `HTTP ${envelope.status}`);
    this.name = "PersonAgentApiError";
    this.envelope = envelope;
    this.status = envelope.status;
    this.retryable = envelope.retryable;
  }
}

export function extractApiErrorEnvelope(
  body: unknown,
  fallbackStatus: number,
  fallbackMessage: string,
): ApiErrorEnvelope {
  const record = isRecord(body) ? body : {};
  const rawError = isRecord(record.error) ? record.error : undefined;
  const message =
    stringValue(rawError?.message) ??
    stringValue(record.detail) ??
    stringValue(record.error) ??
    fallbackMessage ??
    `HTTP ${fallbackStatus}`;
  return {
    code: stringValue(rawError?.code) ?? codeForStatus(fallbackStatus),
    category: stringValue(rawError?.category) ?? categoryForStatus(fallbackStatus),
    severity: stringValue(rawError?.severity) ?? "error",
    message,
    status: numberValue(rawError?.status) ?? fallbackStatus,
    retryable: booleanValue(rawError?.retryable) ?? retryableForStatus(fallbackStatus),
    correlation_id: stringValue(rawError?.correlation_id),
    safe_for_model: booleanValue(rawError?.safe_for_model),
    safe_for_telemetry: booleanValue(rawError?.safe_for_telemetry),
    metadata: isRecord(rawError?.metadata) ? rawError.metadata : undefined,
  };
}

export function errorMessage(error: unknown) {
  if (error instanceof PersonAgentApiError) return error.envelope.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function numberValue(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function booleanValue(value: unknown) {
  return typeof value === "boolean" ? value : undefined;
}

function codeForStatus(status: number) {
  if (status === 401) return "auth.required";
  if (status === 403) return "auth.forbidden";
  if (status === 404) return "request.not_found";
  if (status === 409) return "request.conflict";
  if (status === 429) return "request.rate_limited";
  if (status === 504) return "system.timeout";
  if (status >= 500) return "system.internal_error";
  return "request.error";
}

function categoryForStatus(status: number) {
  if (status === 401 || status === 403) return "auth";
  if (status >= 500) return "system";
  return "request";
}

function retryableForStatus(status: number) {
  return [408, 409, 429, 500, 502, 503, 504].includes(status);
}
