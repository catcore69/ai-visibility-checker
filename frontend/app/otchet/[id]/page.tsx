'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { getReport, getReportPdfUrl, type ReportFull } from '@/lib/api';
import ScoreRing from '@/components/ScoreRing';
import CompetitorChart from '@/components/CompetitorChart';
import ModelBreakdownGrid from '@/components/ModelBreakdown';
import SentimentPie from '@/components/SentimentPie';
import ResponseSamples from '@/components/ResponseSamples';
import RecommendationsBlock from '@/components/RecommendationsBlock';
import FinalCTA from '@/components/FinalCTA';
import { Logo } from '@/components/Logo';

type Section = 'summary' | 'competitors' | 'models' | 'prompts' | 'recommendations';

const NAV_ITEMS: { key: Section; label: string }[] = [
  { key: 'summary', label: 'Итог' },
  { key: 'competitors', label: 'Конкуренты' },
  { key: 'models', label: 'Модели' },
  { key: 'prompts', label: 'Запросы' },
  { key: 'recommendations', label: 'Рекомендации' },
];

function ScoreComponentBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-brand-muted">{label}</span>
        <span className="font-heading text-accent-300">{value}%</span>
      </div>
      <div className="w-full h-1.5 bg-brand-elevated rounded-full overflow-hidden">
        <div
          className="h-full bg-accent-500 rounded-full transition-all duration-700"
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
    </div>
  );
}

function SentimentBadge({ sentiment }: { sentiment?: string }) {
  if (!sentiment) return null;
  const map: Record<string, { label: string; cls: string }> = {
    positive: { label: 'позитив',     cls: 'bg-success/15 text-success border border-success/30' },
    neutral:  { label: 'нейтрально',  cls: 'bg-brand-elevated text-brand-text border border-brand-border' },
    negative: { label: 'негатив',     cls: 'bg-danger/15 text-danger border border-danger/30' },
  };
  const cfg = map[sentiment];
  if (!cfg) return null;
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cfg.cls}`}>{cfg.label}</span>
  );
}

export default function ReportPage() {
  const params = useParams();
  const reportId = params.id as string;

  const [report, setReport] = useState<ReportFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [pdfUrl, setPdfUrl] = useState('');
  const [pdfLoading, setPdfLoading] = useState(false);
  const [activeSection, setActiveSection] = useState<Section>('summary');

  useEffect(() => {
    (async () => {
      try {
        const data = await getReport(reportId);
        setReport(data);
      } catch {
        setError('Не удалось загрузить отчёт. Проверьте ссылку или попробуйте позже.');
      } finally {
        setLoading(false);
      }
    })();
  }, [reportId]);

  const handleDownloadPdf = async () => {
    if (pdfUrl) {
      window.open(pdfUrl, '_blank');
      return;
    }
    setPdfLoading(true);
    try {
      const url = await getReportPdfUrl(reportId);
      setPdfUrl(url);
      window.open(url, '_blank');
    } catch {
      alert('Не удалось получить ссылку на PDF. Попробуйте позже.');
    } finally {
      setPdfLoading(false);
    }
  };

  if (loading) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-brand-bg">
        <div className="flex flex-col items-center gap-4">
          <div className="w-10 h-10 border-2 border-brand-border border-t-accent-400 rounded-full animate-spin" />
          <p className="text-brand-muted text-sm">Загружаем отчёт…</p>
        </div>
      </main>
    );
  }

  if (error || !report) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-brand-bg px-4">
        <div className="text-center">
          <div className="text-accent-400 font-heading text-5xl mb-4">?</div>
          <h1 className="font-heading text-3xl mb-3">Отчёт не найден</h1>
          <p className="text-brand-muted mb-8">{error}</p>
          <a href="/proverka" className="btn-primary inline-flex">
            Новая проверка
          </a>
        </div>
      </main>
    );
  }

  const sc = report.score_components;

  return (
    <main className="min-h-screen bg-brand-bg">
      {/* ── HEADER ── */}
      <header className="border-b border-brand-border/60">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo height={26} />
          <span className="eyebrow hidden sm:inline">AI Visibility Report</span>
        </div>
      </header>

      {/* ── TOP HERO ── */}
      <section className="border-b border-brand-border/60">
        <div className="max-w-5xl mx-auto px-6 py-10">
          <div className="flex flex-col sm:flex-row sm:items-center gap-6">
            <div className="flex-shrink-0">
              <ScoreRing score={report.visibility_score} size={120} />
            </div>

            <div className="flex-1 min-w-0">
              <p className="eyebrow mb-1">AI Visibility Report</p>
              <h1 className="font-heading text-3xl sm:text-4xl truncate mb-1 text-brand-textBright">
                {report.brand_name}
              </h1>
              <p className="text-brand-muted text-sm truncate">{report.website_url}</p>
              <p className="text-brand-text text-sm mt-3 leading-snug max-w-xl">{report.verdict}</p>
            </div>

            <div className="flex-shrink-0">
              <button
                onClick={handleDownloadPdf}
                disabled={pdfLoading}
                className="btn-primary inline-flex items-center gap-2"
              >
                {pdfLoading ? (
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : null}
                Скачать PDF
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-8">
            {[
              { label: 'Presence Rate', value: `${report.presence_rate}%` },
              { label: 'Моделей упоминают', value: `${report.models_found}/${report.models_total}` },
              { label: 'Запросов проверено', value: String(report.prompts_count) },
              { label: 'Место по SoV', value: report.sov_rank ? `#${report.sov_rank}` : '—' },
            ].map((m) => (
              <div key={m.label} className="card-surface p-4 text-center">
                <div className="text-2xl font-heading leading-none mb-1 text-brand-textBright">
                  {m.value}
                </div>
                <div className="eyebrow !text-brand-muted">{m.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── NAVIGATION ── */}
      <nav className="bg-brand-bg/85 backdrop-blur border-b border-brand-border/60 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-6">
          <div className="flex overflow-x-auto">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.key}
                onClick={() => {
                  setActiveSection(item.key);
                  document
                    .getElementById(item.key)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }}
                className={[
                  'px-4 py-4 text-sm whitespace-nowrap border-b-2 transition-colors font-medium',
                  activeSection === item.key
                    ? 'border-accent-500 text-brand-textBright'
                    : 'border-transparent text-brand-muted hover:text-brand-text',
                ].join(' ')}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </nav>

      {/* ── CONTENT ── */}
      <div className="max-w-5xl mx-auto px-6 py-10 flex flex-col gap-12">
        {/* SUMMARY */}
        <section id="summary">
          <p className="eyebrow mb-2">01 — Итог</p>
          <h2 className="font-heading text-2xl mb-6">Сводка по AI Visibility</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <div className="card-surface p-6">
              <h3 className="font-heading text-base mb-4">Из чего складывается Score</h3>
              <div className="flex flex-col gap-3">
                <ScoreComponentBar label="Presence Rate (50%)" value={sc.presence_rate_pct} />
                <ScoreComponentBar label="Model Coverage (20%)" value={sc.model_coverage_pct} />
                <ScoreComponentBar label="Position Score (15%)" value={sc.position_pct} />
                <ScoreComponentBar label="Sentiment Score (15%)" value={sc.sentiment_pct} />
              </div>
            </div>

            <div className="card-surface p-6 flex flex-col gap-4">
              <h3 className="font-heading text-base">Сильные и слабые стороны</h3>
              {report.strong_models.length > 0 && (
                <div>
                  <p className="eyebrow !text-success mb-2">Хорошие позиции</p>
                  <div className="flex flex-wrap gap-2">
                    {report.strong_models.map((m) => (
                      <span
                        key={m}
                        className="bg-success/15 text-success border border-success/30 text-xs font-medium px-3 py-1 rounded-full"
                      >
                        {m}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {report.weak_models.length > 0 && (
                <div>
                  <p className="eyebrow !text-danger mb-2">Требуют внимания</p>
                  <div className="flex flex-wrap gap-2">
                    {report.weak_models.map((m) => (
                      <span
                        key={m}
                        className="bg-danger/15 text-danger border border-danger/30 text-xs font-medium px-3 py-1 rounded-full"
                      >
                        {m}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {report.top_weakness && (
                <div className="border border-warning/30 bg-warning/10 rounded-xl p-3 text-sm text-brand-text">
                  <strong className="text-warning">Главная точка роста:</strong>{' '}
                  {report.top_weakness}
                </div>
              )}
            </div>

            {report.sentiment_breakdown && (
              <div className="card-surface p-6">
                <h3 className="font-heading text-base mb-4">Тональность упоминаний</h3>
                <SentimentPie
                  positive={report.sentiment_breakdown.positive}
                  neutral={report.sentiment_breakdown.neutral}
                  negative={report.sentiment_breakdown.negative}
                />
              </div>
            )}

            {report.expert_note && (
              <div className="card-surface p-6 flex gap-4 border-accent-700/40">
                <div className="w-12 h-12 rounded-full bg-accent-500 text-white flex items-center justify-center font-heading flex-shrink-0">
                  E
                </div>
                <div>
                  <p className="font-heading text-sm text-brand-textBright">Заметка эксперта</p>
                  <p className="eyebrow mb-2">CatCore GEO Studio</p>
                  <p className="text-sm text-brand-text italic leading-relaxed">
                    «{report.expert_note}»
                  </p>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* COMPETITORS */}
        <section id="competitors">
          <p className="eyebrow mb-2">02 — Конкуренты</p>
          <h2 className="font-heading text-2xl mb-6">Кто впереди, кто позади</h2>
          <div className="card-surface p-6">
            <p className="text-sm text-brand-muted mb-5">
              Сравнение с конкурентами по всем {report.prompts_count} запросам и{' '}
              {report.models_total} ИИ-моделям.
            </p>
            <CompetitorChart data={(report.block_a_rows && report.block_a_rows.length > 0) ? report.block_a_rows : report.competitor_comparison} />

            {/* Block A — прямые конкуренты (с fallback на общую таблицу для старых отчётов) */}
            <div className="mt-6 overflow-x-auto">
              <h3 className="font-heading text-lg mb-3 text-brand-textBright">
                Ваши прямые конкуренты
              </h3>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-brand-border">
                    <th className="text-left py-2 px-3 eyebrow">Бренд</th>
                    <th className="text-center py-2 px-3 eyebrow">Score</th>
                    <th className="text-center py-2 px-3 eyebrow">Presence</th>
                    <th className="text-center py-2 px-3 eyebrow">SoV</th>
                    <th className="text-center py-2 px-3 eyebrow">Модели</th>
                    <th className="text-center py-2 px-3 eyebrow">Сент.</th>
                  </tr>
                </thead>
                <tbody>
                  {((report.block_a_rows && report.block_a_rows.length > 0) ? report.block_a_rows : report.competitor_comparison).map((row) => (
                    <tr
                      key={row.name}
                      className={[
                        'border-b border-brand-border/60',
                        row.is_client ? 'bg-accent-700/10' : 'hover:bg-brand-elevated/40',
                      ].join(' ')}
                    >
                      <td className="py-2.5 px-3 font-medium">
                        {row.is_client && <span className="text-accent-300 mr-1">★</span>}
                        <span
                          className={
                            row.is_client
                              ? 'text-brand-textBright font-medium'
                              : 'text-brand-text'
                          }
                        >
                          {row.name}
                        </span>
                        {!row.is_client && row.source_label && (
                          <div className="text-[10px] text-brand-muted mt-0.5">{row.source_label}</div>
                        )}
                      </td>
                      <td
                        className={[
                          'py-2.5 px-3 text-center font-heading',
                          row.is_client ? 'text-accent-300' : 'text-brand-text',
                        ].join(' ')}
                      >
                        {row.score}
                      </td>
                      <td className="py-2.5 px-3 text-center text-brand-text">
                        {row.presence_rate}%
                      </td>
                      <td className="py-2.5 px-3 text-center text-brand-text">{row.sov}%</td>
                      <td className="py-2.5 px-3 text-center text-brand-text">
                        {row.models_found}/{report.models_total}
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <SentimentBadge sentiment={row.dominant_sentiment} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-[11px] text-brand-muted mt-2 leading-relaxed">
                Как подбирали: карточки бизнеса вашего региона (Яндекс / Google Бизнес) →
                поисковая выдача → упоминания в ответах ИИ. У каждой строки — её источник.
              </p>
            </div>

            {/* Площадки-посредники — агрегаторы/каталоги, которых ИИ называет
                вместо отдельных компаний. Не конкуренты, а каналы с комиссией. */}
            {report.intermediary_rows && report.intermediary_rows.length > 0 && (
              <div className="mt-8">
                <h3 className="font-heading text-lg mb-2 text-brand-textBright">
                  Площадки, которые забирают вас в ответах ИИ
                </h3>
                <p className="text-xs text-brand-muted mb-3 leading-relaxed">
                  Когда ваш клиент спрашивает ИИ про вашу нишу, тот часто рекомендует не
                  отдельные компании, а агрегаторы и каталоги. На этих площадках вы платите
                  комиссию за каждого клиента. Наша задача — вывести в ответы ИИ ваш
                  собственный сайт напрямую, без посредников.
                </p>
                <div className="flex flex-wrap gap-2">
                  {report.intermediary_rows.map((it) => (
                    <div
                      key={`im-${it.name}`}
                      className="rounded-lg border border-amber-700/40 bg-amber-900/15 px-3 py-2 text-sm"
                    >
                      <span className="text-amber-200 font-medium">{it.name}</span>
                      {it.kind_label && (
                        <span className="text-[10px] text-amber-300/80 ml-2">{it.kind_label}</span>
                      )}
                      {it.source_label && (
                        <div className="text-[10px] text-brand-muted mt-0.5">{it.source_label}</div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Block B — кого ИИ называет в нише. Показывается ВСЕГДА (даже
                если accepted=0): пустой Блок Б — это валидный сигнал «ниша
                свободна», а не повод его скрывать. */}
            <div className="mt-8 overflow-x-auto">
              <h3 className="font-heading text-lg mb-2 text-brand-textBright">
                Кого ИИ из вашей ниши уже знает
              </h3>
              <p className="text-xs text-brand-muted mb-3">
                Бренды, которых сами ИИ-ассистенты называют в ответах на запросы вашей ниши.
                Это не обязательно ваши прямые конкуренты — часто это крупные федеральные/международные
                игроки или продукты другого типа. Но именно их сейчас слышит ваш потенциальный клиент,
                когда спрашивает ИИ.
              </p>
              {report.block_b_rows && report.block_b_rows.filter((r) => !r.is_client).length > 0 ? (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-brand-border">
                      <th className="text-left py-2 px-3 eyebrow">Бренд</th>
                      <th className="text-center py-2 px-3 eyebrow">Score</th>
                      <th className="text-center py-2 px-3 eyebrow">Presence</th>
                      <th className="text-center py-2 px-3 eyebrow">SoV</th>
                      <th className="text-center py-2 px-3 eyebrow">Модели</th>
                      <th className="text-center py-2 px-3 eyebrow">Сент.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.block_b_rows.filter((r) => !r.is_client).map((row) => (
                      <tr
                        key={`b-${row.name}`}
                        className="border-b border-brand-border/60 hover:bg-brand-elevated/40"
                      >
                        <td className="py-2.5 px-3 font-medium">
                          <span className="text-brand-text">{row.name}</span>
                          {row.other_market_label && (
                            <div className="text-[10px] mt-1 inline-block px-2 py-0.5 rounded bg-amber-900/30 text-amber-300 border border-amber-700/40">
                              {row.other_market_label}
                            </div>
                          )}
                        </td>
                        <td className="py-2.5 px-3 text-center font-heading text-brand-text">{row.score}</td>
                        <td className="py-2.5 px-3 text-center text-brand-text">{row.presence_rate}%</td>
                        <td className="py-2.5 px-3 text-center text-brand-text">{row.sov}%</td>
                        <td className="py-2.5 px-3 text-center text-brand-text">{row.models_found}/{report.models_total}</td>
                        <td className="py-2.5 px-3 text-center"><SentimentBadge sentiment={row.dominant_sentiment} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : report.block_b_state === 'only_other_regions' ? (
                <div className="rounded-lg border border-accent-700/40 bg-accent-700/10 p-5 text-sm text-brand-text leading-relaxed">
                  <p>
                    <strong>В вашей нише ИИ знает только игроков из других регионов
                    и федеральные площадки</strong> — локальных компаний вашего региона
                    он пока не называет. <strong>Место свободно.</strong> Кто первым выстроит
                    правильные сигналы для ИИ в своём регионе, того он и начнёт рекомендовать
                    местным клиентам.
                  </p>
                </div>
              ) : (
                <div className="rounded-lg border border-accent-700/40 bg-accent-700/10 p-5 text-sm text-brand-text leading-relaxed">
                  <p>
                    <strong>ИИ-ассистенты пока не выбрали фаворита в вашей нише</strong>
                    {report.niche ? ` «${report.niche}»` : ''} — не знают ни вас, ни ваших
                    конкурентов. Это <strong>редкое окно</strong>: кто первым выстроит
                    правильные сигналы, того ИИ начнёт рекомендовать. Через год это место
                    будет занято — у конкурентов появится история упоминаний, и перебивать
                    её придётся объёмом.
                  </p>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* MODELS */}
        <section id="models">
          <p className="eyebrow mb-2">03 — Модели</p>
          <h2 className="font-heading text-2xl mb-6">Разбивка по ИИ-ассистентам</h2>
          <ModelBreakdownGrid data={report.model_breakdown} />

          {report.best_responses && report.best_responses.length > 0 && (
            <div className="mt-8">
              <h3 className="font-heading text-base mb-4">Примеры реальных ответов</h3>
              <ResponseSamples responses={report.best_responses} brandName={report.brand_name} />
            </div>
          )}
        </section>

        {/* PROMPTS */}
        <section id="prompts">
          <p className="eyebrow mb-2">04 — Запросы</p>
          <h2 className="font-heading text-2xl mb-6">Матрица упоминаний</h2>

          <div className="card-surface overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-brand-elevated border-b border-brand-border">
                    <th className="text-left py-3 px-4 eyebrow min-w-[220px]">Запрос</th>
                    {report.models_list.map((m) => (
                      <th
                        key={m.model_name}
                        className="text-center py-3 px-2 eyebrow whitespace-nowrap min-w-[80px]"
                      >
                        {m.short_name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.prompts_matrix.map((row, idx) => (
                    <tr
                      key={idx}
                      className={[
                        'border-b border-brand-border/60',
                        idx % 2 === 1 ? 'bg-brand-elevated/30' : '',
                      ].join(' ')}
                    >
                      <td className="py-2 px-4 text-brand-text leading-snug">{row.prompt}</td>
                      {row.cells.map((cell, ci) => (
                        <td key={ci} className="py-2 px-2 text-center">
                          {cell.mentioned && cell.sentiment === 'positive' ? (
                            <span title="Позитивное упоминание" className="text-success">●</span>
                          ) : cell.mentioned && cell.sentiment === 'negative' ? (
                            <span title="Негативное упоминание" className="text-danger">●</span>
                          ) : cell.mentioned ? (
                            <span title="Нейтральное упоминание" className="text-brand-text">●</span>
                          ) : cell.error ? (
                            <span title="Ошибка запроса" className="text-brand-muted">!</span>
                          ) : (
                            <span className="text-brand-muted/40">·</span>
                          )}
                          {cell.position && (
                            <div className="text-brand-muted text-[10px]">#{cell.position}</div>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex flex-wrap gap-4 px-4 py-3 border-t border-brand-border text-xs text-brand-muted">
              <span><span className="text-success">●</span> Позитив</span>
              <span><span className="text-brand-text">●</span> Нейтрально</span>
              <span><span className="text-danger">●</span> Негатив</span>
              <span><span className="text-brand-muted/40">·</span> Не упоминается</span>
            </div>
          </div>

          {(report.top_prompts || report.bottom_prompts) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mt-5">
              {report.top_prompts && report.top_prompts.length > 0 && (
                <div className="card-surface p-5">
                  <p className="eyebrow !text-success mb-3">Лучшие запросы</p>
                  <div className="flex flex-col gap-2">
                    {report.top_prompts.map((p, i) => (
                      <div
                        key={i}
                        className="bg-success/10 border border-success/20 rounded-xl px-3 py-2"
                      >
                        <p className="text-sm font-medium text-brand-text">{p.prompt}</p>
                        <p className="text-xs text-brand-muted mt-0.5">
                          Упоминаний: {p.mention_count}/{report.models_total}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {report.bottom_prompts && report.bottom_prompts.length > 0 && (
                <div className="card-surface p-5">
                  <p className="eyebrow !text-danger mb-3">Приоритеты роста</p>
                  <div className="flex flex-col gap-2">
                    {report.bottom_prompts.map((p, i) => (
                      <div
                        key={i}
                        className="bg-danger/10 border border-danger/20 rounded-xl px-3 py-2"
                      >
                        <p className="text-sm font-medium text-brand-text">{p.prompt}</p>
                        <p className="text-xs text-brand-muted mt-0.5">
                          Упоминаний: {p.mention_count}/{report.models_total}
                          {p.competitor_count > 0 && ` · конкуренты: ${p.competitor_count}`}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        {/* RECOMMENDATIONS */}
        <section id="recommendations">
          <p className="eyebrow mb-2">05 — План действий</p>
          <h2 className="font-heading text-2xl mb-6">Рекомендации</h2>
          <div className="card-surface p-6 mb-6">
            <RecommendationsBlock recommendations={report.recommendations} />
          </div>

          <div className="card-surface p-6 mb-6">
            <h3 className="font-heading text-base mb-4">Ориентировочный план на 90 дней</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {[
                {
                  month: 'Месяц 1',
                  sub: 'Фундамент',
                  items: [
                    'Аудит источников ниши',
                    'Создание 3–5 экспертных материалов',
                    'Настройка структурированных данных',
                  ],
                  growth: '+5–10 баллов',
                },
                {
                  month: 'Месяц 2',
                  sub: 'Распространение',
                  items: [
                    'Публикации в 10+ источниках',
                    'Работа с агрегаторами и Wiki',
                    'Кросс-линкинг упоминаний',
                  ],
                  growth: '+8–15 баллов',
                },
                {
                  month: 'Месяц 3',
                  sub: 'Закрепление',
                  items: [
                    'UGC и работа с отзывами',
                    'Повторный аудит AI Visibility',
                    'Корректировка стратегии',
                  ],
                  growth: '+5–10 баллов',
                },
              ].map((step) => (
                <div key={step.month} className="rounded-2xl p-4 bg-brand-elevated border border-brand-border">
                  <p className="eyebrow text-accent-300 mb-2">{step.month}</p>
                  <p className="font-heading text-sm mb-2">{step.sub}</p>
                  <ul className="flex flex-col gap-1">
                    {step.items.map((item, i) => (
                      <li key={i} className="text-xs text-brand-text flex items-start gap-1.5">
                        <span className="text-accent-400 flex-shrink-0">→</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-xs font-heading text-accent-300">
                    Ожидаемый рост: {step.growth}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <FinalCTA reportId={reportId} brandName={report.brand_name} score={report.visibility_score} />
        </section>

        <section>
          <div className="text-xs text-brand-muted border-t border-brand-border pt-6 leading-relaxed">
            <strong className="text-brand-text">Методология:</strong> AI Visibility Score = Presence
            Rate × 0,50 + Model Coverage × 0,20 + Position Score × 0,15 + Sentiment Score × 0,15.
            Проанализировано {report.models_total} ИИ-ассистентов, {report.prompts_count} запросов.
            Дата: {new Date(report.created_at).toLocaleDateString('ru-RU')}. CatCore GEO Studio.
          </div>
        </section>
      </div>
    </main>
  );
}
