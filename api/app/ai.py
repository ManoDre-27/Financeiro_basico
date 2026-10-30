"""Camada de IA (multi-provedor) do Terminal de Inteligencia Global.

Provedores suportados (por ordem de preferencia, cada um opcional via .env):
  1. Anthropic (Claude)          -> ANTHROPIC_API_KEY
  2. Groq (Llama, GRATIS/rapido) -> GROQ_API_KEY
  3. OpenAI / compativel         -> OPENAI_API_KEY (+ OPENAI_BASE_URL)
  4. Google Gemini (free tier)   -> GEMINI_API_KEY

Fallback automatico: se um provedor falhar (ex: sem creditos), passa ao seguinte.
Um provedor que devolva erro de creditos/quota fica desativado ate reiniciar.

Guardrails (seccao 5 do documento): responde SEMPRE em portugues de Portugal,
so com base no contexto, cita fontes, indica confianca, nunca da conselhos.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select

from .config import settings
from .db import SessionLocal
from .models import NewsArticle, NewsSource, Price, Security

log = logging.getLogger("ai")

SYSTEM_PROMPT = """Es o analista do "Terminal de Inteligencia Global", uma \
infraestrutura pessoal de inteligencia financeira e geopolitica.

Regras invioaveis:
- Responde SEMPRE em portugues de Portugal (nao brasileiro).
- Usa APENAS a informacao do contexto fornecido (noticias e cotacoes reais). Nao inventes numeros nem eventos.
- Cita as fontes que usaste (nome do orgao/ativo). Toda a afirmacao deve ser rastreavel.
- Indica o nivel de confianca: [Confirmado], [Suportado], [Parcial], [Nao confirmado] ou [Especulativo].
- Se a informacao nao existir no contexto, diz "Nao foi possivel verificar com os dados disponiveis".
- Nunca das conselhos de investimento nem dizes o que comprar/vender. Apresentas factos, cenarios e riscos.
- Principio: perceber o mundo primeiro, decidir depois.
- Se texto/orgaos vierem em ingles, resume-os em portugues de Portugal.
"""

# Provedores desativados nesta sessao (ex: apos erro de creditos/quota).
_DISABLED: set[str] = set()


class AIUnavailable(RuntimeError):
    pass


def _is_billing_error(msg: str) -> bool:
    m = msg.lower()
    return any(k in m for k in ("credit balance", "quota", "insufficient", "billing", "exceeded"))


# ----------------------------- Provedores -----------------------------

def _call_anthropic(system: str, user: str, max_tokens: int) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


def _call_openai_compatible(base_url: str, api_key: str, model: str, system: str, user: str, max_tokens: int) -> str:
    r = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=90,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"].strip()


def _call_groq(system: str, user: str, max_tokens: int) -> str:
    return _call_openai_compatible(
        "https://api.groq.com/openai/v1", settings.groq_api_key, settings.groq_model, system, user, max_tokens
    )


def _call_openai(system: str, user: str, max_tokens: int) -> str:
    return _call_openai_compatible(
        settings.openai_base_url, settings.openai_api_key, settings.openai_model, system, user, max_tokens
    )


def _call_gemini(system: str, user: str, max_tokens: int) -> str:
    model = settings.gemini_model
    r = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": settings.gemini_api_key},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        },
        timeout=90,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
    cand = r.json()["candidates"][0]
    return "".join(p.get("text", "") for p in cand["content"]["parts"]).strip()


def _available_providers() -> list[tuple[str, str, callable]]:
    """(nome, modelo, funcao) dos provedores com chave, por ordem de preferencia."""
    out: list[tuple[str, str, callable]] = []
    if settings.anthropic_api_key:
        out.append(("anthropic", settings.anthropic_model, _call_anthropic))
    if settings.groq_api_key:
        out.append(("groq", settings.groq_model, _call_groq))
    if settings.openai_api_key:
        out.append(("openai", settings.openai_model, _call_openai))
    if settings.gemini_api_key:
        out.append(("gemini", settings.gemini_model, _call_gemini))
    # Filtro por preferencia explicita
    if settings.ai_provider != "auto":
        out = [p for p in out if p[0] == settings.ai_provider]
    return [p for p in out if p[0] not in _DISABLED]


def providers_status() -> dict:
    return {
        "enabled": bool(_available_providers()),
        "provider": settings.ai_provider,
        "available": [name for name, _, _ in _available_providers()],
        "configured": {
            "anthropic": bool(settings.anthropic_api_key),
            "groq": bool(settings.groq_api_key),
            "openai": bool(settings.openai_api_key),
            "gemini": bool(settings.gemini_api_key),
        },
    }


LEARN_SYSTEM = """Es um explicador financeiro do "Terminal de Inteligencia Global".
Ensinas conceitos de investimento e economia de forma clara e correta, em portugues
de Portugal (nao brasileiro). Podes usar conhecimento geral para explicar o conceito;
se houver dados no contexto, usa-os como exemplo. Nunca das conselhos de compra/venda."""


def _message(user_text: str, context: str, system: str | None = None) -> dict:
    providers = _available_providers()
    if not providers:
        raise AIUnavailable(
            "Nenhuma IA configurada. Define ANTHROPIC_API_KEY ou uma alternativa gratuita "
            "(GROQ_API_KEY, OPENAI_API_KEY ou GEMINI_API_KEY) no .env."
        )
    full = f"CONTEXTO ATUAL DO TERMINAL:\n{context}\n\n---\nPEDIDO:\n{user_text}"
    errors: list[str] = []
    for name, model, fn in providers:
        try:
            text = fn(system or SYSTEM_PROMPT, full, settings.ai_max_tokens)
            if text:
                return {"text": text, "provider": name, "model": model}
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            log.warning("provedor %s falhou: %s", name, msg)
            errors.append(f"{name}: {msg}")
            if _is_billing_error(msg):
                _DISABLED.add(name)  # nao volta a tentar este nesta sessao
    raise AIUnavailable(
        "Todas as IAs disponiveis falharam. " + " | ".join(errors)
    )


# ----------------------------- Contexto -----------------------------

def _gather_context(news_limit: int = 25) -> str:
    lines: list[str] = []
    with SessionLocal() as db:
        lines.append(f"DATA/HORA (UTC): {datetime.now(timezone.utc).isoformat()}")
        lines.append("\n== COTACOES (ultima conhecida) ==")
        latest_ts = (
            select(Price.security_id, func.max(Price.ts).label("mts"))
            .group_by(Price.security_id)
            .subquery()
        )
        rows = db.execute(
            select(Security, Price)
            .join(Price, Price.security_id == Security.id)
            .join(latest_ts, (latest_ts.c.security_id == Price.security_id) & (latest_ts.c.mts == Price.ts))
            .order_by(Security.asset_class)
        ).all()
        for sec, price in rows:
            chg = f"{price.change_pct:+.2f}%" if price.change_pct is not None else "n/d"
            lines.append(f"- {sec.symbol} ({sec.asset_class}): {price.price} {price.currency or ''} [{chg}]")
        lines.append("\n== NOTICIAS RECENTES ==")
        arts = db.execute(
            select(NewsArticle, NewsSource)
            .join(NewsSource, NewsArticle.source_id == NewsSource.id, isouter=True)
            .order_by(NewsArticle.published_at.desc().nullslast())
            .limit(news_limit)
        ).all()
        for art, src in arts:
            when = art.published_at.strftime("%Y-%m-%d %H:%M") if art.published_at else "s/data"
            lines.append(f"- [{src.name if src else '?'} | {when}] {art.title}")
    return "\n".join(lines)


# ----------------------------- Casos de uso -----------------------------

def ask_terminal(question: str) -> dict:
    r = _message(question, _gather_context(news_limit=30))
    return {"answer": r["text"], "provider": r["provider"], "model": r["model"]}


def fact_check(claim: str) -> dict:
    """Fact Checker (seccao 4.2): verifica uma afirmacao contra as noticias."""
    pedido = (
        f'Verifica esta afirmacao: "{claim}"\n\n'
        "Responde em portugues de Portugal com:\n"
        "1) VEREDITO (escolhe um): Confirmado / Muito suportado / Parcialmente suportado / "
        "Nao confirmado / Contradito.\n"
        "2) Evidencia encontrada no contexto (com as fontes).\n"
        "3) Contradicoes ou lacunas, se existirem.\n"
        "Se o contexto nao tiver informacao, diz 'Nao foi possivel verificar com os dados disponiveis'. "
        "Nao inventes factos."
    )
    r = _message(pedido, _gather_context(news_limit=30))
    return {"answer": r["text"], "provider": r["provider"], "model": r["model"]}


def explain_concept(topic: str) -> dict:
    """Learning Center (seccao 11.4): explica um conceito com exemplo real."""
    pedido = (
        f"Explica de forma simples, em portugues de Portugal, o conceito: {topic}.\n"
        "Usa no maximo 6 frases, linguagem acessivel para quem esta a aprender a investir, "
        "e se possivel liga a um exemplo dos ativos ou noticias do contexto. "
        "Nao des conselhos de compra/venda."
    )
    r = _message(pedido, _gather_context(news_limit=15), system=LEARN_SYSTEM)
    return {"answer": r["text"], "provider": r["provider"], "model": r["model"]}


COMPANY_SYSTEM = """Es um analista de empresas do "Terminal de Inteligencia Global".
Produzes analises qualitativas de empresas em portugues de Portugal (nao brasileiro).
Podes usar conhecimento geral sobre a empresa, MAS deixa claro que nao sao dados
financeiros ao vivo e que numeros concretos devem ser confirmados. Se houver noticias
no contexto sobre a empresa, integra-as. Nunca das conselhos de compra/venda; apresentas
cenarios e riscos com niveis de confianca."""


def company_brief(name: str) -> dict:
    """Company Intelligence (seccao 4.4): dossier qualitativo de uma empresa."""
    pedido = (
        f"Faz um dossier da empresa: {name}.\n"
        "Estrutura em portugues de Portugal:\n"
        "- Visao geral (o que faz)\n"
        "- Modelo de negocio e principais fontes de receita\n"
        "- Posicao competitiva\n"
        "- Cenario BULL (otimista) — porque\n"
        "- Cenario BASE — porque\n"
        "- Cenario BEAR (pessimista) — porque\n"
        "- Principais riscos\n"
        "- Noticias recentes relevantes (se existirem no contexto)\n"
        "Comeca com o aviso: 'Analise qualitativa — nao inclui dados financeiros ao vivo.'"
    )
    r = _message(pedido, _gather_context(news_limit=20), system=COMPANY_SYSTEM)
    return {"answer": r["text"], "provider": r["provider"], "model": r["model"]}


def daily_brief() -> dict:
    pedido = (
        "Faz o *Resumo do Dia* em portugues de Portugal. Estrutura:\n"
        "1) 5 acontecimentos mais importantes (cada um com fonte e nivel de confianca);\n"
        "2) Leitura de mercados (o que os numeros dizem);\n"
        "3) Riscos a vigiar nas proximas horas.\n"
        "Se algo nao estiver no contexto, nao o inventes."
    )
    r = _message(pedido, _gather_context(news_limit=30))
    return {"brief": r["text"], "provider": r["provider"], "model": r["model"]}


def market_impact() -> dict:
    pedido = (
        "Faz a *Leitura do Dia* em portugues de Portugal, em duas partes.\n\n"
        "PARTE 1 - Panorama:\n"
        "- O que esta com VENTO A FAVOR hoje (setores/ativos/temas) e porque, com evidencia e [nivel de confianca].\n"
        "- O que esta com VENTO CONTRA e porque, com evidencia e [nivel de confianca].\n"
        "- O que poderia INVALIDAR esta leitura (o que vigiar).\n\n"
        "PARTE 2 - Impacto por noticia (as mais relevantes):\n"
        "Para cada uma: | Noticia | O que afeta | Pode SUBIR | Pode DESCER | Porque | Confianca |\n"
        "Usa apenas o que esta no contexto; nao inventes numeros.\n\n"
        "Termina com esta frase exata: \"Isto e analise factual e de cenarios, nao e conselho de investimento. Decide tu.\""
    )
    r = _message(pedido, _gather_context(news_limit=30))
    return {"impact": r["text"], "provider": r["provider"], "model": r["model"]}


def _fix_mojibake(s: str) -> str:
    """Repara duplo-encoding UTF-8 (ex: 'mantÃ©m' -> 'mantém') quando presente."""
    if not isinstance(s, str) or not any(m in s for m in ("Ã", "Â", "â\x82", "â\x80")):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _extract_json_array(text: str) -> list:
    """Extrai um array JSON da resposta do modelo (tolera ```json e texto a volta)."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("resposta sem array JSON")
    return json.loads(cleaned[start : end + 1])


def daily_highlights() -> dict:
    """Destaques do dia em formato estruturado, para mostrar como pop-ups.

    NAO sao recomendacoes de compra: sao sinais factuais (oportunidade/risco) com
    o porque, nivel de confianca e fontes, para o utilizador analisar.
    """
    pedido = (
        "Com base APENAS no contexto, identifica ate 5 DESTAQUES do dia relevantes para quem "
        "acompanha investimentos (temas, setores, ativos, regioes). NAO recomendes comprar/vender "
        "nem prometas lucro; apenas indica o mercado exposto e a direcao plausivel do impacto.\n"
        "Para cada destaque diz qual o MERCADO/MOEDA/ATIVO concreto mais exposto (de preferencia dos que "
        "seguimos: Bitcoin, Ethereum, EUR/USD, Petroleo/Brent, Ouro, bolsa portuguesa/europeia, ou uma acao "
        "citada como a Mota-Engil) e se esse mercado tende a subir ou descer com esta noticia.\n"
        "Responde APENAS com um array JSON valido, sem texto a volta, neste formato:\n"
        '[{"titulo":"...","tipo":"oportunidade" ou "risco","mercado":"ativo/mercado exposto",'
        '"direcao":"pode subir" ou "pode descer" ou "misto",'
        '"porque":"1 frase em portugues de Portugal","confianca":"Confirmado|Suportado|Parcial|Especulativo",'
        '"fontes":["orgao1","orgao2"]}]\n'
        "Usa so informacao do contexto; nao inventes numeros nem ativos."
    )
    r = _message(pedido, _gather_context(news_limit=30))
    try:
        items = _extract_json_array(r["text"])
    except Exception as exc:  # noqa: BLE001
        log.warning("highlights JSON invalido: %s", exc)
        items = []
    # Normaliza e limita a 5
    out = []
    for it in items[:5]:
        if not isinstance(it, dict):
            continue
        fontes = it.get("fontes", []) if isinstance(it.get("fontes"), list) else []
        out.append(
            {
                "titulo": _fix_mojibake(str(it.get("titulo", "")))[:140],
                "tipo": it.get("tipo", "oportunidade"),
                "mercado": _fix_mojibake(str(it.get("mercado", "")))[:60],
                "direcao": it.get("direcao", ""),
                "porque": _fix_mojibake(str(it.get("porque", "")))[:300],
                "confianca": it.get("confianca", ""),
                "fontes": [_fix_mojibake(str(f)) for f in fontes],
            }
        )
    return {"highlights": out, "provider": r["provider"], "model": r["model"]}
