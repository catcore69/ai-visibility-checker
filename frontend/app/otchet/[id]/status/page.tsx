'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { getReportStatus, type ReportStatus } from '@/lib/api';
import ProgressTracker from '@/components/ProgressTracker';

const POLL_INTERVAL  = 5_000;  // 5 seconds
const MAX_WAIT_MS    = 15 * 60 * 1000; // 15 minutes max polling

export default function StatusPage() {
  const params = useParams();
  const router = useRouter();
  const reportId = params.id as string;

  const [status,    setStatus]    = useState<ReportStatus | null>(null);
  const [error,     setError]     = useState('');
  const [startedAt] = useState(Date.now());

  const poll = useCallback(async () => {
    try {
      const data = await getReportStatus(reportId);
      setStatus(data);

      if (data.status === 'done') {
        router.replace(`/otchet/${reportId}`);
        return;
      }

      if (data.status === 'error') {
        setError('Произошла ошибка при формировании отчёта. Попробуйте снова.');
        return;
      }

      // Check max wait time
      if (Date.now() - startedAt > MAX_WAIT_MS) {
        setError('Анализ занимает дольше обычного. Проверьте почту — мы пришлём отчёт, как только он будет готов.');
        return;
      }
    } catch {
      // Network errors are transient — keep polling
    }
  }, [reportId, router, startedAt]);

  useEffect(() => {
    poll();
    const interval = setInterval(poll, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [poll]);

  if (error) {
    return (
      <main className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
        <div className="max-w-md w-full text-center">
          <div className="text-5xl mb-6">😔</div>
          <h1 className="text-2xl font-black text-gray-900 mb-4">Что-то пошло не так</h1>
          <p className="text-gray-600 mb-8">{error}</p>
          <a
            href="/proverka"
            className="inline-flex items-center gap-2 bg-blue-600 text-white font-bold px-6 py-3 rounded-xl hover:bg-blue-700 transition-colors"
          >
            ← Попробовать снова
          </a>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gradient-to-b from-blue-50 to-white flex flex-col items-center justify-center px-4">
      <div className="max-w-xl w-full">
        {/* Header */}
        <div className="text-center mb-10">
          <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-5 text-2xl">
            🔍
          </div>
          <h1 className="text-3xl font-black text-gray-900 mb-3">
            Анализируем ваш бренд
          </h1>
          <p className="text-gray-600">
            Опрашиваем 7 ИИ-ассистентов и анализируем упоминания.
            Это займёт 3–7 минут.
          </p>
        </div>

        {/* Progress */}
        {status ? (
          <ProgressTracker status={status} />
        ) : (
          <div className="flex justify-center">
            <div className="w-10 h-10 border-3 border-blue-200 border-t-blue-600 rounded-full animate-spin" />
          </div>
        )}

        {/* Footer */}
        <p className="text-center text-xs text-gray-400 mt-10">
          Результат также будет отправлен на вашу почту ·{' '}
          <a href="/proverka" className="text-blue-600 hover:underline">
            Начать новую проверку
          </a>
        </p>
      </div>
    </main>
  );
}
