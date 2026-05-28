import axios from 'axios';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || '';

export const api = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
});

// ─── Types ──────────────────────────────────────────────────────────────────

export interface CheckPayload {
  url: string;
  email: string;
  /** Бренд и ниша больше НЕ вводятся в форме — определяются парсингом сайта
      (Задача 5.1). Оставлены опциональными для обратной совместимости. */
  brand_name?: string;
  niche?: string;
  /** Задача 5.2 — ссылки на сайты конкурентов (по одной на строку, до 5). */
  client_competitors?: string[];
  /** Этап 1.4 ТЗ — оба обязательны на форме, бэк проверяет повторно. */
  consent_personal_data: boolean;
  consent_cross_border: boolean;
  turnstile_token: string;
  fingerprint_id: string;
  /** Honeypot – must be empty */
  hp_name?: string;
  utm_source?: string;
  utm_medium?: string;
  utm_campaign?: string;
}

export interface CheckResponse {
  report_id: string;
  /** "pending_verification" — нужна верификация; "completed" — отчёт уже готов (дедуп по домену). */
  status?: string;
  message: string;
  queue_position?: number;
}

export interface ReportStatus {
  /** UUID отчёта (от бэка — `id`). */
  id?: string;
  report_id?: string;

  /** Любой из статусов pipeline (см. backend/app/core/pipeline.py). */
  status: string;

  /** Прогресс 0–100 (поле бэка — `progress`). */
  progress?: number;
  progress_pct?: number;

  message?: string;
  current_step?: string;
  completed?: boolean;
  failed?: boolean;
  error?: string | null;

  queue_position?: number;
  estimated_wait_seconds?: number;
}

export interface ModelBreakdown {
  model_name: string;
  display_name: string;
  presence_rate: number;
  mentions: number;
  prompts_tested: number;
  avg_position?: number | null;
  dominant_sentiment?: string;
  positive_count?: number;
  neutral_count?: number;
  negative_count?: number;
}

export interface CompetitorRow {
  name: string;
  is_client: boolean;
  score: number;
  presence_rate: number;
  sov: number;
  models_found: number;
  dominant_sentiment: string;
}

export interface PromptMatrixCell {
  model_name: string;
  mentioned: boolean;
  sentiment?: string;
  position?: number | null;
  error?: boolean;
}

export interface PromptMatrixRow {
  prompt: string;
  cells: PromptMatrixCell[];
}

export interface Recommendation {
  title: string;
  description: string;
  effort: 'low' | 'medium' | 'high';
  impact?: string;
  action_items?: string[];
}

export interface ReportFull {
  report_id: string;
  brand_name: string;
  website_url: string;
  niche: string;
  created_at: string;
  visibility_score: number;
  presence_rate: number;
  verdict: string;
  models_found: number;
  models_total: number;
  prompts_count: number;
  sov_rank?: number;
  competitors_count: number;
  strong_models: string[];
  weak_models: string[];
  top_weakness?: string;
  competitor_comparison: CompetitorRow[];
  model_breakdown: ModelBreakdown[];
  prompts_matrix: PromptMatrixRow[];
  models_list: { model_name: string; display_name: string; short_name: string }[];
  top_prompts?: { prompt: string; mention_count: number; avg_sentiment?: string }[];
  bottom_prompts?: { prompt: string; mention_count: number; competitor_count: number }[];
  recommendations: Recommendation[];
  expert_note?: string;
  score_components: {
    presence_rate_pct: number;
    model_coverage_pct: number;
    position_pct: number;
    sentiment_pct: number;
  };
  sentiment_breakdown?: {
    positive: number;
    neutral: number;
    negative: number;
    positive_pct: number;
    neutral_pct: number;
    negative_pct: number;
  };
  best_responses?: {
    model_name: string;
    model_display_name: string;
    model_css_class: string;
    prompt: string;
    response_excerpt: string;
    brand_mentioned: boolean;
    position?: number;
    sentiment?: string;
  }[];
  pdf_url?: string;
}

// ─── API helpers ─────────────────────────────────────────────────────────────

export async function submitCheck(payload: CheckPayload): Promise<CheckResponse> {
  const { data } = await api.post<CheckResponse>('/check', payload);
  return data;
}

export async function getReportStatus(reportId: string): Promise<ReportStatus> {
  const { data } = await api.get<ReportStatus>(`/report/${reportId}/status`);
  return data;
}

export async function getReport(reportId: string): Promise<ReportFull> {
  const { data } = await api.get<ReportFull>(`/report/${reportId}`);
  return data;
}

export async function getReportPdfUrl(reportId: string): Promise<string> {
  const { data } = await api.get<{ url: string }>(`/report/${reportId}/pdf`);
  return data.url;
}

export async function trackCta(reportId: string, action: string): Promise<void> {
  await api.post(`/report/${reportId}/cta`, { action });
}

export interface ContactPayload {
  name: string;
  phone?: string;
  telegram?: string;
  preferred_time?: string;
  consent_personal_data: boolean;
  consent_cross_border: boolean;
}

export async function addContact(
  reportId: string,
  payload: ContactPayload,
): Promise<{ status: string; spam_suspect: boolean }> {
  const { data } = await api.post(`/report/${reportId}/contact`, payload);
  return data;
}

export async function resendEmail(reportId: string): Promise<void> {
  await api.post(`/check/${reportId}/resend-email`);
}
