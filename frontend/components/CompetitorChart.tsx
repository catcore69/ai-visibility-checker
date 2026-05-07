'use client';

import type { CompetitorRow } from '@/lib/api';

interface Props {
  data: CompetitorRow[];
}

export default function CompetitorChart({ data }: Props) {
  const sorted = [...data].sort((a, b) => b.score - a.score);
  const maxScore = Math.max(...sorted.map(d => d.score), 100);

  return (
    <div className="flex flex-col gap-3">
      {sorted.map((row, idx) => (
        <div key={row.name} className="flex items-center gap-3">
          {/* Rank */}
          <span
            className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${
              row.is_client
                ? 'bg-blue-600 text-white'
                : idx === 0
                ? 'bg-yellow-400 text-white'
                : 'bg-gray-100 text-gray-500'
            }`}
          >
            {idx + 1}
          </span>

          {/* Name */}
          <div className="w-28 flex-shrink-0">
            <span
              className={`text-sm truncate block ${
                row.is_client ? 'font-bold text-blue-600' : 'text-gray-700'
              }`}
            >
              {row.is_client ? '⭐ ' : ''}
              {row.name}
            </span>
          </div>

          {/* Bar */}
          <div className="flex-1 h-7 bg-gray-100 rounded-full overflow-hidden relative">
            <div
              className={`h-full rounded-full flex items-center px-3 transition-all duration-700 ${
                row.is_client ? 'bg-blue-600' : 'bg-gray-300'
              }`}
              style={{ width: `${(row.score / maxScore) * 100}%`, minWidth: '20px' }}
            />
          </div>

          {/* Score */}
          <span
            className={`w-10 text-right text-sm font-bold flex-shrink-0 ${
              row.is_client ? 'text-blue-600' : 'text-gray-600'
            }`}
          >
            {row.score}
          </span>

          {/* SoV */}
          <span className="w-14 text-right text-xs text-gray-400 flex-shrink-0">
            SoV {row.sov}%
          </span>
        </div>
      ))}
    </div>
  );
}
