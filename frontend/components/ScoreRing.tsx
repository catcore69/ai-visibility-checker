'use client';

import { useEffect, useState } from 'react';

interface Props {
  score: number;
  size?: number;
  strokeWidth?: number;
}

function getScoreColor(score: number): string {
  if (score >= 70) return '#34C759';
  if (score >= 45) return '#FF9500';
  return '#FF3B30';
}

function getScoreLabel(score: number): string {
  if (score >= 80) return 'Отлично';
  if (score >= 60) return 'Хорошо';
  if (score >= 40) return 'Средне';
  if (score >= 20) return 'Низко';
  return 'Критично';
}

export default function ScoreRing({ score, size = 160, strokeWidth = 12 }: Props) {
  const [animated, setAnimated] = useState(0);

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (animated / 100) * circumference;
  const color = getScoreColor(score);

  useEffect(() => {
    const timer = setTimeout(() => setAnimated(score), 100);
    return () => clearTimeout(timer);
  }, [score]);

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} className="rotate-[-90deg]">
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#E5E5EA"
          strokeWidth={strokeWidth}
        />
        {/* Progress circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 1.2s ease-out' }}
        />
      </svg>
      {/* Center text (overlaid) */}
      <div
        className="flex flex-col items-center justify-center"
        style={{ marginTop: -(size), height: size }}
      >
        <span
          className="font-black leading-none"
          style={{ fontSize: size * 0.22, color }}
        >
          {score}
        </span>
        <span className="text-xs text-gray-500 mt-1">/ 100</span>
        <span className="text-xs font-semibold mt-0.5" style={{ color }}>
          {getScoreLabel(score)}
        </span>
      </div>
    </div>
  );
}
