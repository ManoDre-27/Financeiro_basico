export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Market = {
  symbol: string;
  name: string | null;
  asset_class: string | null;
  price: number;
  change_pct: number | null;
  currency: string | null;
  trend: "up" | "down" | "flat";
  ts: string;
};

export type HistoryPoint = { ts: string; price: number };
export const getMarketHistory = (symbol: string, minutes = 1440) =>
  get<{ symbol: string; points: HistoryPoint[] }>(
    `/api/markets/${encodeURIComponent(symbol)}/history?minutes=${minutes}`,
  );
export const addMarket = (symbol: string) =>
  post<{ ok: boolean; symbol: string; asset_class: string }>("/api/markets/add", { symbol });

export type NewsItem = {
  title: string;
  link: string;
  summary: string | null;
  source: string | null;
  published_at: string | null;
};

export type Health = {
  status: string;
  engine: string;
  now: string;
  counts: { prices: number; news: number };
  last_ingest: { markets: string | null; news: string | null };
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export const getMarkets = () => get<Market[]>("/api/markets");
export const getNews = () => get<NewsItem[]>("/api/news?limit=30");
export const getHealth = () => get<Health>("/health");

export type AIStatus = {
  enabled: boolean;
  provider: string;
  available: string[];
  configured: Record<string, boolean>;
};
export const getAIStatus = () => get<AIStatus>("/api/ai/status");

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.detail || `${path} -> ${res.status}`);
  return data as T;
}

type AIResp = { provider: string; model: string } & Record<string, string>;
export const askTerminal = (question: string) =>
  post<AIResp>("/api/ai/ask", { question });
export const generateBrief = () => post<AIResp>("/api/ai/brief");
export const generateImpact = () => post<AIResp>("/api/ai/impact");
export const factCheck = (claim: string) => post<AIResp>("/api/ai/factcheck", { claim });
export const learnConcept = (topic: string) => post<AIResp>("/api/ai/learn", { topic });
export const companyBrief = (name: string) => post<AIResp>("/api/ai/company", { name });

export type Position = {
  symbol: string;
  quantity: number;
  avg_cost: number;
  price: number | null;
  market_value: number;
  pnl: number;
  pnl_pct: number | null;
};
export type Portfolio = {
  cash: number;
  initial_cash: number;
  holdings_value: number;
  total_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  positions: Position[];
};
export type StoredBrief = { content: string | null; provider?: string; created_at?: string };
export const getStoredBrief = () => get<StoredBrief>("/api/reports/daily_brief");
export const generateStoredBrief = () => post<StoredBrief>("/api/reports/daily_brief/generate");

export const getPortfolio = () => get<Portfolio>("/api/portfolio");
export const tradePortfolio = (symbol: string, side: "buy" | "sell", quantity: number) =>
  post<{ ok: boolean }>("/api/portfolio/trade", { symbol, side, quantity });
export const resetPortfolio = () => post<{ ok: boolean }>("/api/portfolio/reset");

export type Highlight = {
  titulo: string;
  tipo: "oportunidade" | "risco" | string;
  mercado: string;
  direcao: string;
  porque: string;
  confianca: string;
  fontes: string[];
};
export const getHighlights = () =>
  get<{ highlights: Highlight[]; provider: string }>("/api/ai/highlights");
