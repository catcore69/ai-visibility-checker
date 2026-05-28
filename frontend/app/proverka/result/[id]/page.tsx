'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { getReport, getReportPdfUrl, trackCta, type ReportFull } from '@/lib/api';
import ScoreRing from '@/components/ScoreRing';
import { Logo } from '@/components/Logo';

/**
 * Страница-тизер результата (Этап 5.3 ТЗ).
 *
 * Короткое превью (страницы 1–2 PDF): Score, вердикт, ключевые цифры, главный
 * разрыв. Цель — клиент видит результат сразу, без открытия почты, и идёт в
 * один из двух CTA. Полный разбор — на /otchet/{id}.
 */
export default function ResultTeaserPage() {
  const params = useParams();
  const reportId = params.id as string;

  const [report, setReport] = useState<ReportFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [pdfLoading, setPdfLoading] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        setReport(await getReport(reportId));
      } catch {
        setError('Не удалось загрузить результат. Проверьте ссылку.');
      } finally {
        setLoading(false);
      }
    })();
  }, [reportId]);

  const handlePdf = async () => {
    setPdfLoading(true);
    try {
      const url = await getReportPdfUrl(reportId);
      window.open(url, '_blank');
    } catch {
      alert('Не удалось получить PDF. Попробуйте позже.');
    } finally {
      setPdfLoading(false);
    }
  };

  if (loading) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-brand-bg">
        <div className="w-10 h-10 border-2 border-brand-border border-t-accent-400 rounded-full animate-spin" />
      </main>
    );
  }

  if (error || !report) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-brand-bg px-4">
        <div className="text-center">
          <h1 className="font-heading text-2xl mb-3">Результат не найден</h1>
          <p className="text-brand-muted mb-6">{error}</p>
          <a href="/proverka" className="btn-primary inline-flex">Новая проверка</a>
        </div>
      </main>
    );
  }

  const verdict =
    report.visibility_score < 31
      ? 'Ваш бренд почти невидим для ИИ'
      : report.visibility_score < 61
        ? 'ИИ знает о вас, но рекомендует других'
        : 'Вы в игре — есть куда расти';

  const bookingUrl = `/zapis-na-razgovor?report_id=${reportId}&utm_source=ai_report&utm_campaign=cta_call_result_page`;

  return (
    <main className="min-h-screen bg-brand-bg text-brand-text">
      <header className="border-b border-brand-border/60">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo height={26} />
          <span className="eyebrow hidden sm:inline">Результат проверки</span>
        </div>
      </header>

      <section className="max-w-3xl mx-auto px-6 py-14">
        {/* Score + вердикт */}
        <div className="card-surface p-8 flex flex-col sm:flex-row items-center gap-8 text-center sm:text-left">
          <div className="flex-shrink-0">
            <ScoreRing score={report.visibility_score} size={140} />
          </div>
          <div>
            <p className="eyebrow mb-2">{report.brand_name}</p>
            <h1 className="font-heading text-2xl sm:text-3xl leading-tight mb-2">{verdict}</h1>
            <p className="text-brand-muted text-sm">{report.website_url}</p>
          </div>
        </div>

        {/* Ключевые цифры */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
          {[
            { label: 'Presence Rate', value: `${report.presence_rate}%` },
            { label: 'Моделей упоминают', value: `${report.models_found}/${report.models_total}` },
            { label: 'Запросов', value: String(report.prompts_count) },
            { label: 'Место по SoV', value: report.sov_rank ? `#${report.sov_rank}` : '—' },
          ].map((m) => (
            <div key={m.label} className="card-surface p-4 text-center">
              <div className="text-2xl font-heading leading-none mb-1 text-brand-textBright">{m.value}</div>
              <div className="eyebrow !text-brand-muted">{m.label}</div>
            </div>
          ))}
        </div>

        {/* Главный разрыв */}
        {report.top_weakness && (
          <div className="card-surface p-5 mt-5 border-warning/30">
            <p className="eyebrow !text-warning mb-1">Главная точка роста</p>
            <p className="text-sm text-brand-text">{report.top_weakness}</p>
          </div>
        )}

        {/* CTA */}
        <div className="flex flex-col sm:flex-row gap-3 mt-8">
          <a
            href={bookingUrl}
            onClick={() => trackCta(reportId, 'call').catch(() => {})}
            className="btn-primary flex-1 inline-flex items-center justify-center"
          >
            Выбрать время разговора
          </a>
          <button
            onClick={handlePdf}
            disabled={pdfLoading}
            className="btn-secondary flex-1 inline-flex items-center justify-center"
          >
            {pdfLoading ? 'Готовим…' : 'Скачать полный PDF'}
          </button>
        </div>

        <p className="text-center text-sm text-brand-muted mt-6">
          Хотите детальный разбор по всем моделям и конкурентам?{' '}
          <a href={`/otchet/${reportId}`} className="text-accent-400 hover:underline">
            Открыть полный отчёт →
          </a>
        </p>
      </section>
    </main>
  );
}
