'use client';

import type { CompetitorRow } from '@/lib/api';

interface Props {
  data: CompetitorRow[];
}

/**
 * Горизонтальный бар-чарт сравнения с конкурентами.
 * Клиент выделен акцентным красным, остальные — нейтральным серым.
 */
export default function CompetitorChart({ data }: Props) {
  const sorted = [...data].sort((a, b) => b.score - a.score);
  const maxScore = Math.max(...sorted.map((d) => d.score), 100);

  return (
    <div className="flex flex-col gap-3">
      {sorted.map((row, idx) => (
        <div key={row.name} className="flex items-center gap-3">
          <span
            className={[
              'w-7 h-7 rounded-full flex items-center justify-center text-xs font-heading flex-shrink-0 border',
              row.is_client
                ? 'bg-accent-500 border-accent-500 text-white'
                : idx === 0
                  ? 'bg-warning/15 border-warning/40 text-warning'
                  : 'bg-brand-surface border-brand-border text-brand-muted',
            ].join(' ')}
          >
            {idx + 1}
          </span>

          <div className="w-32 flex-shrink-0">
            <span
              className={[
                'text-sm truncate block',
                row.is_client ? 'font-medium text-brand-textBright' : 'text-brand-text',
              ].join(' ')}
            >
              {row.is_client ? '★ ' : ''}
              {row.name}
            </span>
          </div>

          <div className="flex-1 h-6 bg-brand-surface border border-brand-border rounded-full overflow-hidden">
            <div
              className={[
                'h-full rounded-full transition-all duration-700',
                row.is_client ? 'bg-accent-500' : 'bg-brand-elevated',
              ].join(' ')}
              style={{ width: `${(row.score / maxScore) * 100}%`, minWidth: '20px' }}
            />
          </div>

          <span
            className={[
              'w-10 text-right text-sm font-heading flex-shrink-0',
              row.is_client ? 'text-accent-300' : 'text-brand-text',
            ].join(' ')}
          >
            {row.score}
          </span>
          <span className="w-14 text-right text-xs text-brand-muted flex-shrink-0">
            SoV {row.sov}%
          </span>
        </div>
      ))}
    </div>
  );
}
