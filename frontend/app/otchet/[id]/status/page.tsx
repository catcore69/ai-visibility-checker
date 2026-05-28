'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { getReportStatus, type ReportStatus } from '@/lib/api';
import ProgressTracker from '@/components/ProgressTracker';
import ExpertCallBlock from '@/components/ExpertCallBlock';
import { Logo } from '@/components/Logo';

const POLL_INTERVAL = 5_000;
const MAX_WAIT_MS = 15 * 60 * 1000;
// Этап 5.2.2 ТЗ: блок сбора контактов появляется только после 70% прогресса.
const CONTACT_BLOCK_THRESHOLD = 70;

export default function StatusPage() {
  const params = useParams();
  const router = useRouter();
  const reportId = params.id as string;

  const [status, setStatus] = useState<ReportStatus | null>(null);
  const [error, setError] = useState('');
  const [startedAt] = useState(Date.now());
  // Состояние блока «Хочу комментарий эксперта»: показан ли он и закрыт ли клиентом.
  const [contactResolved, setContactResolved] = useState(false);

  const poll = useCallback(async () => {
    try {
      const data = await getReportStatus(reportId);
      setStatus(data);

      const READY_STATUSES = ['awaiting_personal_note', 'sending_email', 'completed'];
      if (READY_STATUSES.includes(data.status) || (data as any).completed === true) {
        router.replace(`/otchet/${reportId}`);
        return;
      }

      if (data.status === 'failed' || data.status === 'error' || (data as any).failed === true) {
        setError(
          (data as any).error ||
            'Произошла ошибка при формировании отчёта. Попробуйте снова.',
        );
        return;
      }

      if (Date.now() - startedAt > MAX_WAIT_MS) {
        setError(
          'Анализ занимает дольше обычного. Проверьте почту — мы пришлём отчёт, как только он будет готов.',
        );
        return;
      }
    } catch {
      // транзиентные ошибки сети — продолжаем поллинг
    }
  }, [reportId, router, startedAt]);

  useEffect(() => {
    poll();
    const interval = setInterval(poll, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [poll]);

  if (error) {
    return (
      <main className="min-h-screen bg-brand-bg flex flex-col">
        <header className="border-b border-brand-border/60">
          <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
            <Logo height={26} />
          </div>
        </header>
        <section className="flex-1 flex items-center justify-center px-6 py-16">
          <div className="max-w-md w-full text-center">
            <div className="text-accent-400 font-heading text-5xl mb-6">!</div>
            <h1 className="font-heading text-3xl mb-4">Что-то пошло не так</h1>
            <p className="text-brand-muted mb-8">{error}</p>
            <a href="/proverka" className="btn-primary inline-flex">
              Попробовать снова
            </a>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-brand-bg flex flex-col">
      <header className="border-b border-brand-border/60">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo height={26} />
          <span className="eyebrow hidden sm:inline">CatCore GEO Studio</span>
        </div>
      </header>

      <section className="flex-1 flex flex-col items-center justify-center px-6 py-16">
        <div className="max-w-xl w-full">
          <div className="text-center mb-10">
            <div className="inline-flex items-center gap-2 border border-brand-border bg-brand-surface px-3 py-1.5 rounded-full mb-6">
              <span className="w-1.5 h-1.5 rounded-full bg-accent-500 pulse-dot" />
              <span className="eyebrow !text-brand-text">Анализ в процессе</span>
            </div>
            <h1 className="font-heading text-3xl sm:text-4xl mb-3">Анализируем ваш бренд</h1>
            <p className="text-brand-muted">
              Опрашиваем ИИ-ассистенты и анализируем упоминания. Это займёт 3–7 минут.
            </p>
          </div>

          {status ? (
            <ProgressTracker status={status} />
          ) : (
            <div className="flex justify-center">
              <div className="w-10 h-10 border-2 border-brand-border border-t-accent-400 rounded-full animate-spin" />
            </div>
          )}

          {/* Этап 5.2.2 ТЗ: блок «Хочу комментарий эксперта» появляется после 70%. */}
          {status &&
            !contactResolved &&
            ((status as any).progress ?? status.progress_pct ?? 0) >= CONTACT_BLOCK_THRESHOLD && (
              <div className="mt-8">
                <ExpertCallBlock
                  reportId={reportId}
                  onResolved={() => setContactResolved(true)}
                />
              </div>
            )}

          <p className="text-center text-xs text-brand-muted mt-10">
            Результат также будет отправлен на вашу почту ·{' '}
            <a href="/proverka" className="text-accent-400 hover:underline">
              Начать новую проверку
            </a>
          </p>
        </div>
      </section>
    </main>
  );
}
