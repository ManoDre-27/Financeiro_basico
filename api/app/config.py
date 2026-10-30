"""Configuracao central do Terminal de Inteligencia Global (MVP).

Le variaveis do ambiente (.env). Sem Postgres definido, cai para SQLite local
para que o terminal corra de imediato numa maquina de desenvolvimento.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Le .env da pasta api/ e tambem o .env da raiz do projeto (Docker/local).
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # Vazio => usa SQLite local (./data/terminal.db). Em Docker/Proxmox aponta
    # para o Postgres, ex: postgresql+psycopg://user:pass@postgres:5432/terminal
    database_url: str = ""

    # Intervalos de ingestao (segundos). Curtos para o MVP; o doc preve 1-5 min.
    market_interval_seconds: int = 300
    news_interval_seconds: int = 300

    # Watchlist inicial. Cripto (CoinGecko) e FX (Frankfurter) tem dados fiaveis
    # em qualquer rede; acoes/indices/commodities dependem do acesso ao Yahoo.
    tickers: str = (
        "BTC-USD,ETH-USD,SOL-USD,XRP-USD,ADA-USD,DOGE-USD,BNB-USD,DOT-USD,LTC-USD,"
        "EURUSD=X,GBPUSD=X,USDJPY=X,EURGBP=X,USDCHF=X,EURBRL=X,"
        "AAPL,MSFT,NVDA,TSLA,^GSPC,^IXIC,GC=F,CL=F"
    )

    # Feeds RSS de noticias em portugues de Portugal (fontes publicas gratuitas).
    rss_feeds: str = (
        "https://eco.sapo.pt/feed/,"
        "https://www.jornaldenegocios.pt/rss,"
        "https://www.rtp.pt/noticias/rss/economia"
    )

    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- IA (multi-provedor) ---
    # "auto" tenta os provedores por ordem; ou fixa um: anthropic|groq|openai|gemini
    ai_provider: str = "auto"
    # Maximo de tokens por resposta. Nao existe "ilimitado"; sobe conforme o plano.
    ai_max_tokens: int = 4096

    # Anthropic (Claude) - pago
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # Groq (Llama) - GRATIS, rapido, sem cartao. Chave em https://console.groq.com
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"

    # OpenAI ou compativel (ex: OpenRouter). Base URL configuravel.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # Google Gemini - free tier. Chave em https://aistudio.google.com/apikey
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    @property
    def ticker_list(self) -> list[str]:
        return [t.strip() for t in self.tickers.split(",") if t.strip()]

    @property
    def feed_list(self) -> list[str]:
        return [f.strip() for f in self.rss_feeds.split(",") if f.strip()]

    @property
    def cors_list(self) -> list[str]:
        return [c.strip() for c in self.cors_origins.split(",") if c.strip()]


settings = Settings()
