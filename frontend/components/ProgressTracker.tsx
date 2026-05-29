'use client';

import { useEffect, useState } from 'react';
import { STEP_LABELS, STEP_PROGRESS, STEP_INDEX, LOADING_FACTS } from '@/lib/loading-facts';
import type { ReportStatus } from '@/lib/api';

interface Props {
  status: ReportStatus;
}

const FACT_INTERVAL = 8000;

export default function ProgressTracker({ status }: Props) {
  const [factIndex, setFactIndex] = useState(0);
  const [facts] = useState(() => [...LOADING_FACTS].sort(() => Math.random() - 0.5));

  useEffect(() => {
    const interval = setInterval(() => {
      setFactIndex((i) => (i + 1) % facts.length);
    }, FACT_INTERVAL);
    return () => clearInterval(interval);
  }, [facts]);

  const currentStep = status.current_step ?? status.status;
  const stepLabel = STEP_LABELS[currentStep] ?? 'Обрабатываем…';
  const progress =
    (status as any).progress ?? status.progress_pct ?? STEP_PROGRESS[currentStep] ?? 5;
  const isDoneAll = currentStep === 'completed' || (status as any).completed === true;

  // Итерация-3: порядок шагов соответствует новому pipeline
  // (опрос идёт ДО подбора конкурентов — конкуренты из реальных ответов ИИ).
  const steps = [
    { key: 'niche_detection', label: 'Определение ниши' },
    { key: 'prompt_generation', label: 'Генерация запросов' },
    { key: 'polling_models', label: 'Опрос ИИ-ассистентов' },
    { key: 'competitor_discovery', label: 'Поиск конкурентов' },
    { key: 'analyzing_responses', label: 'Анализ упоминаний' },
    { key: 'building_pdf', label: 'Формирование отчёта' },
  ];

  const currentStepIndex = isDoneAll ? steps.length : STEP_INDEX[currentStep] ?? -1;

  return (
    <div className="w-full max-w-xl mx-auto flex flex-col gap-6">
      {/* Progress bar */}
      <div>
        <div className="flex justify-between text-sm mb-2">
          <span className="font-medium text-brand-text">{stepLabel}</span>
          <span className="font-heading text-accent-400">{progress}%</span>
        </div>
        <div className="w-full h-2 bg-brand-surface border border-brand-border rounded-full overflow-hidden">
          <div
            className="h-full bg-accent-500 rounded-full transition-all duration-700 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
        {status.estimated_wait_seconds && progress < 95 && (
          <p className="text-xs text-brand-muted mt-1.5 text-right">
            Ещё ~{Math.ceil(status.estimated_wait_seconds / 60)} мин.
          </p>
        )}
      </div>

      {/* Step list */}
      <div className="flex flex-col gap-2">
        {steps.map((step, idx) => {
          const isDone = currentStepIndex > idx || isDoneAll;
          const isActive = currentStepIndex === idx && !isDoneAll;
          return (
            <div key={step.key} className="flex items-center gap-3">
              <div
                className={[
                  'w-7 h-7 rounded-full flex items-center justify-center text-sm flex-shrink-0 transition-colors border',
                  isDone
                    ? 'bg-accent-700 border-accent-700 text-white'
                    : isActive
                      ? 'bg-accent-500 border-accent-500 text-white pulse-dot'
                      : 'bg-brand-surface border-brand-border text-brand-muted',
                ].join(' ')}
              >
                {isDone ? '✓' : idx + 1}
              </div>
              <span
                className={[
                  'text-sm',
                  isDone
                    ? 'text-brand-muted line-through'
                    : isActive
                      ? 'text-brand-text font-medium'
                      : 'text-brand-muted',
                ].join(' ')}
              >
                {step.label}
              </span>
            </div>
          );
        })}
      </div>

      {currentStep === 'awaiting_personal_note' && (
        <div className="card-surface px-4 py-3 text-sm text-brand-text">
          Отчёт почти готов — эксперт добавляет персональную заметку. Это занимает до{' '}
          {Math.ceil(((status as any).estimated_wait_seconds ?? 30 * 60) / 60)} минут. Письмо
          придёт сразу после отправки.
        </div>
      )}

      {status.queue_position && status.queue_position > 1 && (
        <div className="card-surface px-4 py-3 text-sm text-brand-text">
          Вы в очереди: позиция <strong className="text-accent-300">#{status.queue_position}</strong>. Как
          только дойдёт очередь — запустим анализ автоматически.
        </div>
      )}

      <div className="card-surface p-5 min-h-[80px] flex items-start gap-3">
        <span className="font-heading text-accent-400 text-sm flex-shrink-0">FACT</span>
        <div>
          <p className="eyebrow mb-1">Знаете ли вы?</p>
          <p className="text-sm text-brand-text leading-relaxed">{facts[factIndex % facts.length]}</p>
        </div>
      </div>
    </div>
  );
}
