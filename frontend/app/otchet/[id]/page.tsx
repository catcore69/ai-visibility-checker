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

type Section =
  | 'summary'
  | 'competitors'
  | 'models'
  | 'prompts'
  | 'recommendations';

const NAV_ITEMS: { key: Section; label: string; icon: string }[] = [
  { key: 'summary',         label: 'Итог',          icon: '📊' },
  { key: 'competitors',     label: 'Конкуренты',    icon: '🏆' },
  { key: 'models',          label: 'Модели',         icon: '🤖' },
  { key: 'prompts',         label: 'Запросы',        icon: '💬' },
  { key: 'recommendations', label: 'Рекомендации',   icon: '🎯' },
];

function ScoreComponentBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-600">{label}</span>
        <span className="font-bold text-blue-600">{value}%</span>
      </div>
      <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-600 rounded-full transition-all duration-700"
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
    </div>
  );
}

function SentimentBadge({ sentiment }: { sentiment?: string }) {
  if (!sentiment) return null;
  const map: Record<string, { label: string; cls: string }> = {
    positive: { label: 'позитив',    cls: 'bg-green-100 text-green-700' },
    neutral:  { label: 'нейтрально', cls: 'bg-gray-100 text-gray-600'  },
    negative: { label: 'негатив',    cls: 'bg-red-100 text-red-600'    },
  };
  const cfg = map[sentiment];
  if (!cfg) return null;
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

export default function ReportPage() {
  const params   = useParams();
  const reportId = params.id as string;

  const [report,   setReport]   = useState<ReportFull | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState('');
  const [pdfUrl,   setPdfUrl]   = useState('');
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
    if (pdfUrl) { window.open(pdfUrl, '_blank'); return; }
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
      <main className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-blue-100 border-t-blue-600 rounded-full animate-spin" />
          <p className="text-gray-500 text-sm">Загружаем отчёт...</p>
        </div>
      </main>
    );
  }

  if (error || !report) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <div className="text-center">
          <div className="text-5xl mb-4">😕</div>
          <h1 className="text-2xl font-black text-gray-900 mb-3">Отчёт не найден</h1>
          <p className="text-gray-600 mb-8">{error}</p>
          <a href="/proverka" className="bg-blue-600 text-white font-bold px-6 py-3 rounded-xl hover:bg-blue-700 transition-colors">
            ← Новая проверка
          </a>
        </div>
      </main>
    );
  }

  const sc = report.score_components;

  return (
    <main className="min-h-screen bg-gray-50">
      {/* ── TOP HEADER ── */}
      <div className="bg-gradient-to-r from-blue-700 to-blue-900 text-white">
        <div className="max-w-5xl mx-auto px-4 py-8">
          <div className="flex flex-col sm:flex-row sm:items-center gap-6">
            {/* Score ring */}
            <div className="flex-shrink-0">
              <ScoreRing score={report.visibility_score} size={120} />
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <p className="text-blue-200 text-sm font-medium mb-1">AI Visibility Report</p>
              <h1 className="text-3xl font-black truncate mb-1">{report.brand_name}</h1>
              <p className="text-blue-200 text-sm truncate">{report.website_url}</p>
              <p className="text-blue-100 text-sm mt-2 italic leading-snug">
                {report.verdict}
              </p>
            </div>

            {/* PDF button */}
            <div className="flex-shrink-0">
              <button
                onClick={handleDownloadPdf}
                disabled={pdfLoading}
                className="flex items-center gap-2 bg-white text-blue-700 font-bold px-5 py-3 rounded-xl hover:bg-blue-50 transition-colors text-sm disabled:opacity-60"
              >
                {pdfLoading ? (
                  <span className="w-4 h-4 border-2 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
                ) : (
                  '📄'
                )}
                Скачать PDF
              </button>
            </div>
          </div>

          {/* Key metrics row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-8">
            {[
              { label: 'Presence Rate',     value: `${report.presence_rate}%`                   },
              { label: 'Моделей упоминают', value: `${report.models_found}/${report.models_total}` },
              { label: 'Запросов проверено',value: String(report.prompts_count)                  },
              { label: 'Место по SoV',      value: report.sov_rank ? `#${report.sov_rank}` : '—' },
            ].map(m => (
              <div key={m.label} className="bg-white/10 rounded-2xl p-4 text-center">
                <div className="text-2xl font-black leading-none mb-1">{m.value}</div>
                <div className="text-xs text-blue-200">{m.label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── NAVIGATION ── */}
      <div className="bg-white border-b border-gray-100 sticky top-0 z-10 shadow-sm">
        <div className="max-w-5xl mx-auto px-4">
          <nav className="flex overflow-x-auto">
            {NAV_ITEMS.map(item => (
              <button
                key={item.key}
                onClick={() => {
                  setActiveSection(item.key);
                  document.getElementById(item.key)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }}
                className={`flex items-center gap-1.5 px-4 py-4 text-sm font-semibold whitespace-nowrap border-b-2 transition-colors ${
                  activeSection === item.key
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-800'
                }`}
              >
                {item.icon} {item.label}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {/* ── CONTENT ── */}
      <div className="max-w-5xl mx-auto px-4 py-8 flex flex-col gap-10">

        {/* ── SUMMARY ── */}
        <section id="summary">
          <h2 className="text-xl font-black text-gray-900 mb-5">📊 Сводка</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* Score components */}
            <div className="bg-white rounded-2xl p-6 border border-gray-100">
              <h3 className="font-bold text-gray-900 mb-4">Из чего складывается Score</h3>
              <div className="flex flex-col gap-3">
                <ScoreComponentBar label="Presence Rate (50%)"    value={sc.presence_rate_pct}   />
                <ScoreComponentBar label="Model Coverage (20%)"   value={sc.model_coverage_pct}  />
                <ScoreComponentBar label="Position Score (15%)"   value={sc.position_pct}        />
                <ScoreComponentBar label="Sentiment Score (15%)"  value={sc.sentiment_pct}       />
              </div>
            </div>

            {/* Strong/weak models */}
            <div className="bg-white rounded-2xl p-6 border border-gray-100 flex flex-col gap-4">
              <h3 className="font-bold text-gray-900 mb-1">Сильные и слабые стороны</h3>
              {report.strong_models.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-green-600 uppercase tracking-wide mb-2">✅ Хорошие позиции</p>
                  <div className="flex flex-wrap gap-2">
                    {report.strong_models.map(m => (
                      <span key={m} className="bg-green-50 text-green-700 text-xs font-semibold px-3 py-1 rounded-full">{m}</span>
                    ))}
                  </div>
                </div>
              )}
              {report.weak_models.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-red-500 uppercase tracking-wide mb-2">⚠️ Требуют внимания</p>
                  <div className="flex flex-wrap gap-2">
                    {report.weak_models.map(m => (
                      <span key={m} className="bg-red-50 text-red-600 text-xs font-semibold px-3 py-1 rounded-full">{m}</span>
                    ))}
                  </div>
                </div>
              )}
              {report.top_weakness && (
                <div className="bg-yellow-50 border border-yellow-100 rounded-xl p-3 text-sm text-yellow-800">
                  <strong>Главная точка роста:</strong> {report.top_weakness}
                </div>
              )}
            </div>

            {/* Sentiment */}
            {report.sentiment_breakdown && (
              <div className="bg-white rounded-2xl p-6 border border-gray-100">
                <h3 className="font-bold text-gray-900 mb-4">Тональность упоминаний</h3>
                <SentimentPie
                  positive={report.sentiment_breakdown.positive}
                  neutral={report.sentiment_breakdown.neutral}
                  negative={report.sentiment_breakdown.negative}
                />
              </div>
            )}

            {/* Expert note */}
            {report.expert_note && (
              <div className="bg-gradient-to-br from-blue-50 to-green-50 border border-blue-100 rounded-2xl p-6 flex gap-4">
                <div className="w-12 h-12 rounded-full bg-blue-600 text-white flex items-center justify-center text-lg font-black flex-shrink-0">
                  E
                </div>
                <div>
                  <p className="font-bold text-gray-900 text-sm">Заметка эксперта</p>
                  <p className="text-xs text-gray-500 mb-2">Cat Core GEO Studio</p>
                  <p className="text-sm text-gray-700 italic leading-relaxed">«{report.expert_note}»</p>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* ── COMPETITORS ── */}
        <section id="competitors">
          <h2 className="text-xl font-black text-gray-900 mb-5">🏆 Конкурентный анализ</h2>
          <div className="bg-white rounded-2xl p-6 border border-gray-100">
            <p className="text-sm text-gray-500 mb-5">
              Сравнение с конкурентами по всем {report.prompts_count} запросам и {report.models_total} ИИ-моделям.
            </p>
            <CompetitorChart data={report.competitor_comparison} />

            {/* Detail table */}
            <div className="mt-6 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-left py-2 px-3 text-xs text-gray-400 font-semibold">Бренд</th>
                    <th className="text-center py-2 px-3 text-xs text-gray-400 font-semibold">Score</th>
                    <th className="text-center py-2 px-3 text-xs text-gray-400 font-semibold">Presence</th>
                    <th className="text-center py-2 px-3 text-xs text-gray-400 font-semibold">SoV</th>
                    <th className="text-center py-2 px-3 text-xs text-gray-400 font-semibold">Модели</th>
                    <th className="text-center py-2 px-3 text-xs text-gray-400 font-semibold">Сент.</th>
                  </tr>
                </thead>
                <tbody>
                  {report.competitor_comparison.map(row => (
                    <tr
                      key={row.name}
                      className={`border-b border-gray-50 ${row.is_client ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
                    >
                      <td className="py-2.5 px-3 font-medium">
                        {row.is_client && <span className="text-blue-600 mr-1">⭐</span>}
                        <span className={row.is_client ? 'text-blue-700 font-bold' : 'text-gray-800'}>
                          {row.name}
                        </span>
                      </td>
                      <td className={`py-2.5 px-3 text-center font-bold ${row.is_client ? 'text-blue-600' : 'text-gray-700'}`}>
                        {row.score}
                      </td>
                      <td className="py-2.5 px-3 text-center text-gray-600">{row.presence_rate}%</td>
                      <td className="py-2.5 px-3 text-center text-gray-600">{row.sov}%</td>
                      <td className="py-2.5 px-3 text-center text-gray-600">{row.models_found}/{report.models_total}</td>
                      <td className="py-2.5 px-3 text-center">
                        <SentimentBadge sentiment={row.dominant_sentiment} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* ── MODELS ── */}
        <section id="models">
          <h2 className="text-xl font-black text-gray-900 mb-5">🤖 Разбивка по ИИ-ассистентам</h2>
          <ModelBreakdownGrid data={report.model_breakdown} />

          {/* Response samples */}
          {report.best_responses && report.best_responses.length > 0 && (
            <div className="mt-6">
              <h3 className="font-bold text-gray-900 mb-4">💬 Примеры реальных ответов</h3>
              <ResponseSamples responses={report.best_responses} brandName={report.brand_name} />
            </div>
          )}
        </section>

        {/* ── PROMPTS ── */}
        <section id="prompts">
          <h2 className="text-xl font-black text-gray-900 mb-5">💬 Детали по запросам</h2>

          {/* Matrix table */}
          <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-100">
                    <th className="text-left py-3 px-4 font-semibold text-gray-500 min-w-[220px]">
                      Запрос
                    </th>
                    {report.models_list.map(m => (
                      <th key={m.model_name} className="text-center py-3 px-2 font-semibold text-gray-500 whitespace-nowrap min-w-[80px]">
                        {m.short_name}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.prompts_matrix.map((row, idx) => (
                    <tr key={idx} className={`border-b border-gray-50 ${idx % 2 === 1 ? 'bg-gray-50/50' : ''}`}>
                      <td className="py-2 px-4 text-gray-700 leading-snug">{row.prompt}</td>
                      {row.cells.map((cell, ci) => (
                        <td key={ci} className="py-2 px-2 text-center">
                          {cell.mentioned && cell.sentiment === 'positive' ? (
                            <span title="Позитивное упоминание" className="text-base">✅</span>
                          ) : cell.mentioned && cell.sentiment === 'negative' ? (
                            <span title="Негативное упоминание" className="text-base">⚠️</span>
                          ) : cell.mentioned ? (
                            <span title="Нейтральное упоминание" className="text-base">➖</span>
                          ) : cell.error ? (
                            <span title="Ошибка запроса" className="text-gray-400">!</span>
                          ) : (
                            <span className="text-gray-300">·</span>
                          )}
                          {cell.position && (
                            <div className="text-gray-400 text-[10px]">#{cell.position}</div>
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Legend */}
            <div className="flex flex-wrap gap-4 px-4 py-3 border-t border-gray-100 text-xs text-gray-500">
              <span>✅ Позитив</span>
              <span>➖ Нейтрально</span>
              <span>⚠️ Негатив</span>
              <span className="text-gray-300">·</span><span>Не упоминается</span>
            </div>
          </div>

          {/* Best / Worst prompts */}
          {(report.top_prompts || report.bottom_prompts) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mt-5">
              {report.top_prompts && report.top_prompts.length > 0 && (
                <div className="bg-white rounded-2xl p-5 border border-gray-100">
                  <h3 className="font-bold text-green-600 text-sm mb-3">🏆 Лучшие запросы</h3>
                  <div className="flex flex-col gap-2">
                    {report.top_prompts.map((p, i) => (
                      <div key={i} className="bg-green-50 border border-green-100 rounded-xl px-3 py-2">
                        <p className="text-sm font-medium text-gray-800">{p.prompt}</p>
                        <p className="text-xs text-gray-500 mt-0.5">
                          Упоминаний: {p.mention_count}/{report.models_total}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {report.bottom_prompts && report.bottom_prompts.length > 0 && (
                <div className="bg-white rounded-2xl p-5 border border-gray-100">
                  <h3 className="font-bold text-red-500 text-sm mb-3">⚡ Приоритеты роста</h3>
                  <div className="flex flex-col gap-2">
                    {report.bottom_prompts.map((p, i) => (
                      <div key={i} className="bg-red-50 border border-red-100 rounded-xl px-3 py-2">
                        <p className="text-sm font-medium text-gray-800">{p.prompt}</p>
                        <p className="text-xs text-gray-500 mt-0.5">
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

        {/* ── RECOMMENDATIONS ── */}
        <section id="recommendations">
          <h2 className="text-xl font-black text-gray-900 mb-5">🎯 Рекомендации</h2>
          <div className="bg-white rounded-2xl p-6 border border-gray-100 mb-6">
            <RecommendationsBlock recommendations={report.recommendations} />
          </div>

          {/* Road map */}
          <div className="bg-white rounded-2xl p-6 border border-gray-100 mb-6">
            <h3 className="font-bold text-gray-900 mb-4">🗺️ Ориентировочный план на 90 дней</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {[
                { month: 'Месяц 1', sub: 'Фундамент',      icon: '🏗️', items: ['Аудит источников ниши', 'Создание 3–5 экспертных материалов', 'Настройка структурированных данных'], growth: '+5–10 баллов' },
                { month: 'Месяц 2', sub: 'Распространение', icon: '📡', items: ['Публикации в 10+ источниках', 'Работа с агрегаторами и Wiki', 'Кросс-линкинг упоминаний'],             growth: '+8–15 баллов' },
                { month: 'Месяц 3', sub: 'Закрепление',     icon: '🔒', items: ['UGC и работа с отзывами', 'Повторный аудит AI Visibility', 'Корректировка стратегии'],               growth: '+5–10 баллов' },
              ].map(step => (
                <div key={step.month} className="bg-blue-50 rounded-2xl p-4 border border-blue-100">
                  <div className="text-2xl mb-2">{step.icon}</div>
                  <p className="font-bold text-gray-900 text-sm">{step.month} — {step.sub}</p>
                  <ul className="mt-2 flex flex-col gap-1">
                    {step.items.map((item, i) => (
                      <li key={i} className="text-xs text-gray-600 flex items-start gap-1.5">
                        <span className="text-blue-400 flex-shrink-0">→</span>{item}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-xs font-bold text-blue-600">Ожидаемый рост: {step.growth}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Final CTA */}
          <FinalCTA
            reportId={reportId}
            brandName={report.brand_name}
            score={report.visibility_score}
          />
        </section>

        {/* Methodology */}
        <section>
          <div className="text-xs text-gray-400 border-t border-gray-100 pt-6 leading-relaxed">
            <strong>Методология:</strong> AI Visibility Score = Presence Rate × 0,50 + Model Coverage × 0,20 +
            Position Score × 0,15 + Sentiment Score × 0,15. Проанализировано {report.models_total} ИИ-ассистентов,{' '}
            {report.prompts_count} запросов. Дата: {new Date(report.created_at).toLocaleDateString('ru-RU')}.{' '}
            Инструмент от Cat Core GEO Studio.
          </div>
        </section>
      </div>
    </main>
  );
}
