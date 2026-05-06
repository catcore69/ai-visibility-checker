"""Сборка PDF-отчёта через WeasyPrint + Jinja2, загрузка в S3."""

import base64
import io
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.config import settings
from app.core.analyzer import Analysis
from app.core.scorer import (
    compare_with_competitors,
    get_model_breakdown,
    get_top_sources,
)
from app.storage.s3_client import S3Client
from app.utils.logger import get_logger

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


def _score_color(score: int) -> str:
    if score >= 60:
        return "#34C759"
    if score >= 30:
        return "#FF9500"
    return "#FF3B30"


def _make_score_chart(score: int) -> str:
    """Рисует круговой gauge для Score, возвращает base64 PNG."""
    fig, ax = plt.subplots(figsize=(4, 4), subplot_kw={"aspect": "equal"})

    color = _score_color(score)
    remaining = 100 - score

    wedges, _ = ax.pie(
        [score, remaining],
        startangle=90,
        colors=[color, "#F2F2F7"],
        wedgeprops={"width": 0.4, "edgecolor": "white", "linewidth": 2},
    )

    ax.text(0, 0, str(score), ha="center", va="center", fontsize=36, fontweight="bold", color=color)
    ax.text(0, -0.35, "/ 100", ha="center", va="center", fontsize=14, color="#8E8E93")

    plt.tight_layout(pad=0)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _make_competitor_chart(comparison: list[dict]) -> str:
    """Bar chart сравнения брендов, возвращает base64 PNG."""
    fig, ax = plt.subplots(figsize=(8, max(3, len(comparison) * 0.8)))

    brands = [c["brand_name"] for c in reversed(comparison)]
    scores = [c["score"] for c in reversed(comparison)]
    colors = ["#0066FF" if c["is_client"] else "#C7C7CC" for c in reversed(comparison)]

    bars = ax.barh(brands, scores, color=colors, height=0.6, edgecolor="none")

    for bar, score in zip(bars, scores):
        ax.text(
            bar.get_width() + 0.5,
            bar.get_y() + bar.get_height() / 2,
            str(score),
            va="center",
            fontsize=11,
            color="#1C1C1E",
        )

    ax.set_xlim(0, 105)
    ax.set_xlabel("AI Visibility Score", fontsize=11)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.axvline(x=50, color="#FF9500", linestyle="--", alpha=0.5, linewidth=1)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _make_sentiment_pie(analysis: Analysis, brand_name: str) -> str:
    """Pie chart тональности упоминаний, возвращает base64 PNG."""
    brand_results = [r for r in analysis.get_brand_results(brand_name) if r.mentioned]
    sentiments = [r.sentiment for r in brand_results]

    pos = sentiments.count("positive")
    neu = sentiments.count("neutral")
    neg = sentiments.count("negative")

    if not (pos + neu + neg):
        pos, neu, neg = 0, 1, 0

    fig, ax = plt.subplots(figsize=(4, 4))
    labels = ["Позитивные", "Нейтральные", "Негативные"]
    sizes = [pos, neu, neg]
    colors = ["#34C759", "#8E8E93", "#FF3B30"]
    explode = (0.05, 0, 0.05)

    ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        explode=explode,
        autopct="%1.0f%%",
        startangle=90,
        textprops={"fontsize": 11},
    )

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def _get_worst_prompts(
    analysis: Analysis, brand_name: str, competitors: list[str], count: int = 5
) -> list[dict]:
    """Промпты, где конкуренты упоминаются, а бренд клиента — нет."""
    worst = []
    all_prompts = {r.prompt for r in analysis.all_results}

    for prompt in all_prompts:
        client_mentioned = any(
            r.mentioned for r in analysis.get_brand_results(brand_name) if r.prompt == prompt
        )
        if client_mentioned:
            continue

        # Собираем упоминания конкурентов в этом промпте
        competitor_mentions = []
        for comp in competitors:
            for r in analysis.get_brand_results(comp):
                if r.prompt == prompt and r.mentioned:
                    competitor_mentions.append(
                        {
                            "brand": comp,
                            "model": r.model_name,
                            "context": r.context,
                            "sentiment": r.sentiment,
                        }
                    )
        if competitor_mentions:
            worst.append({"prompt": prompt, "competitor_mentions": competitor_mentions[:3]})

    return worst[:count]


def _mark_competitors_red(text: str, competitors: list[str]) -> str:
    """Выделяет упоминания конкурентов красным цветом в HTML."""
    import re

    for comp in competitors:
        pattern = re.compile(re.escape(comp), re.IGNORECASE)
        text = pattern.sub(
            f'<span style="color:#FF3B30; font-weight:bold;">{comp}</span>', text
        )
    return text


async def build_and_upload_pdf(report, analysis: Analysis, competitors: list[str]) -> str:
    """Собирает PDF-отчёт, загружает в S3, возвращает URL."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    env.filters["mark_competitors_red"] = lambda text: _mark_competitors_red(
        text, competitors
    )

    brand_name = report.brand_name
    score = report.visibility_score or 0
    niche = report.niche_data or {}
    all_brands = [brand_name] + competitors

    comparison = compare_with_competitors(analysis, brand_name, all_brands)
    model_breakdown = get_model_breakdown(analysis, brand_name)
    top_sources = get_top_sources(analysis)
    worst_prompts = _get_worst_prompts(analysis, brand_name, competitors)

    # Графики
    score_chart_b64 = _make_score_chart(score)
    competitor_chart_b64 = _make_competitor_chart(comparison)
    sentiment_chart_b64 = _make_sentiment_pie(analysis, brand_name)

    context = {
        # Основные данные
        "report": report,
        "brand_name": brand_name,
        "score": score,
        "score_color": _score_color(score),
        "score_label": "Низкая" if score < 30 else "Средняя" if score < 60 else "Высокая",
        "report_date": datetime.now().strftime("%d.%m.%Y"),
        "niche": niche,
        "region": report.region,
        "competitors": competitors,
        "recommendations": report.recommendations or [],
        "expert_note": report.expert_note,

        # Аналитика
        "comparison": comparison,
        "model_breakdown": model_breakdown,
        "top_sources": top_sources[:10],
        "worst_prompts": worst_prompts,
        "presence_rate": report.presence_rate or 0,
        "share_of_voice": report.share_of_voice or 0,

        # Графики (base64 PNG)
        "score_chart_b64": score_chart_b64,
        "competitor_chart_b64": competitor_chart_b64,
        "sentiment_chart_b64": sentiment_chart_b64,

        # Студия и эксперт
        "EXPERT_NAME": settings.EXPERT_NAME,
        "EXPERT_TITLE": settings.EXPERT_TITLE,
        "EXPERT_PHOTO_URL": settings.EXPERT_PHOTO_URL,
        "STUDIO_NAME": settings.STUDIO_NAME,
        "STUDIO_FULL_URL": settings.STUDIO_FULL_URL,
        "STUDIO_LOGO_URL": settings.STUDIO_LOGO_URL,
        "CONTACT_TG_BOT_URL": settings.CONTACT_TG_BOT_URL,
        "CONTACT_EMAIL": settings.CONTACT_EMAIL,
    }

    template = env.get_template("report.html")
    html_content = template.render(**context)

    # WeasyPrint рендер
    pdf_bytes = HTML(string=html_content, base_url=str(TEMPLATES_DIR)).write_pdf()

    # Загрузка в S3
    s3 = S3Client()
    key = f"reports/{report.id}.pdf"
    pdf_url = await s3.upload_bytes(key, pdf_bytes, content_type="application/pdf")

    # Сохраняем ключ в report
    from app.db.session import AsyncSessionLocal
    from app.db.repositories.report_repo import update_report_field
    async with AsyncSessionLocal() as db:
        await update_report_field(db, report.id, pdf_s3_key=key, pdf_url=pdf_url)

    logger.info("pdf_built", report_id=str(report.id), size=len(pdf_bytes))
    return pdf_url
