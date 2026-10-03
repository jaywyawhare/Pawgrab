/**
 * Pawgrab TypeScript SDK — official client for the Pawgrab web scraping API.
 *
 * Zero dependencies (uses the global fetch available in Node 18+ and all
 * modern runtimes). Covers scrape, parse, crawl, search, extract, and map.
 */

export interface ScrapeOptions {
  formats?: Array<"markdown" | "html" | "text" | "json" | "csv" | "xml">;
  wait_for_js?: boolean | null;
  timeout?: number;
  include_metadata?: boolean;
  summary?: boolean;
  question?: string | null;
  highlights?: boolean;
  actions?: Array<Record<string, unknown>>;
  css_selector?: string | null;
  excluded_tags?: string[] | null;
  excluded_selector?: string | null;
  follow_next?: number;
  session_id?: string | null;
  cache_ttl?: number | null;
  [key: string]: unknown;
}

export interface ScrapeResponse {
  success: boolean;
  url: string;
  markdown?: string | null;
  html?: string | null;
  text?: string | null;
  json_data?: unknown[] | null;
  metadata?: Record<string, unknown> | null;
  summary?: string | null;
  answer?: string | null;
  highlights?: string[] | null;
  warnings?: string[];
  error?: string | null;
  [key: string]: unknown;
}

export interface ParseOptions {
  url?: string | null;
  formats?: Array<"markdown" | "html" | "text" | "json" | "csv" | "xml">;
  css_selector?: string | null;
  excluded_tags?: string[] | null;
  excluded_selector?: string | null;
}

export interface ExtractOptions {
  prompt: string;
  schema_hint?: Record<string, unknown> | null;
  json_schema?: Record<string, unknown> | null;
  auto_schema?: boolean;
}

export interface SearchOptions {
  num_results?: number;
  formats?: Array<"markdown" | "html" | "text" | "json" | "csv" | "xml">;
  include_domains?: string[] | null;
  exclude_domains?: string[] | null;
  scrape?: boolean;
  category?: "general" | "news" | "images" | "videos";
}

export interface CrawlOptions {
  max_pages?: number;
  max_depth?: number;
  allowed_domains?: string[] | null;
  formats?: Array<"markdown" | "html" | "text" | "json" | "csv" | "xml">;
}

export interface CrawlJob {
  job_id: string;
  status: "queued" | "in_progress" | "completed" | "failed" | "cancelled";
  total_urls: number;
}

export class PawgrabError extends Error {
  readonly code: string | null;
  readonly status: number;

  constructor(message: string, status: number, code: string | null) {
    super(message);
    this.name = "PawgrabError";
    this.status = status;
    this.code = code;
  }
}

const DEFAULT_TIMEOUT_MS = 120_000;

export class PawgrabClient {
  private readonly baseUrl: string;
  private readonly apiKey: string | null;

  constructor(baseUrl = "http://localhost:8000", apiKey: string | null = null) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.apiKey = apiKey || process.env.PAWGRAB_API_KEY || null;
  }

  private async request<T>(path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.apiKey) headers["Authorization"] = `Bearer ${this.apiKey}`;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS);
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${path}`, {
        method: body === undefined ? "GET" : "POST",
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new PawgrabError(
        (data as { error?: string }).error ?? `Request failed (${res.status})`,
        res.status,
        (data as { code?: string }).code ?? null,
      );
    }
    return data as T;
  }

  async health(): Promise<Record<string, unknown>> {
    return this.request("/health");
  }

  async scrape(url: string, options: ScrapeOptions = {}): Promise<ScrapeResponse> {
    return this.request("/v1/scrape", { url, ...options });
  }

  /** Run raw HTML through the extraction pipeline without fetching. */
  async parse(html: string, options: ParseOptions = {}): Promise<ScrapeResponse> {
    return this.request("/v1/parse", { html, ...options });
  }

  async crawl(url: string, options: CrawlOptions = {}): Promise<CrawlJob> {
    return this.request("/v1/crawl", { url, ...options });
  }

  async crawlStatus(jobId: string): Promise<CrawlJob & { results?: ScrapeResponse[] }> {
    return this.request(`/v1/crawl/${encodeURIComponent(jobId)}`);
  }

  /** Start a crawl and poll until it finishes. */
  async crawlAndWait(url: string, options: CrawlOptions = {}, pollMs = 2000): Promise<CrawlJob & { results?: ScrapeResponse[] }> {
    let job = await this.crawl(url, options);
    while (job.status === "queued" || job.status === "in_progress") {
      await new Promise((r) => setTimeout(r, pollMs));
      job = await this.crawlStatus(job.job_id);
    }
    return job;
  }

  async search(query: string, options: SearchOptions = {}): Promise<Record<string, unknown>> {
    return this.request("/v1/search", { query, ...options });
  }

  async extract(url: string, options: ExtractOptions): Promise<Record<string, unknown>> {
    return this.request("/v1/extract", { url, ...options });
  }

  async map(url: string, options: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    return this.request("/v1/map", { url, ...options });
  }
}

export default PawgrabClient;
