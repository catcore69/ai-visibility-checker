import type { Config } from 'tailwindcss';

/**
 * Дизайн-система CatCore GEO Studio.
 *
 * Веб-страницы (этот фронт): тёмная тема — самый тёмный фон брендбука.
 * PDF-отчёт: светлый фон (см. backend/templates/report.html).
 * Красный — только акцентный цвет: CTA-кнопки, критичные сигналы, "когти".
 */
const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Brand palette
        brand: {
          bg: '#0E0F12',        // самый тёмный — фон страниц
          surface: '#1B1D22',   // карточки, поля ввода
          elevated: '#2A2D34',  // hover/выделение карточек
          border: '#2F333B',    // тонкие разделители
          muted: '#8A8F99',     // вторичный текст
          text: '#E6E8EC',      // основной текст
          textBright: '#FFFFFF',
        },
        // Accent red (минимально, для CTA и сигналов)
        accent: {
          DEFAULT: '#A63D3D',
          50:  '#F6E4E4',
          100: '#ECC6C6',
          200: '#D89494',
          300: '#C46666',
          400: '#B93A3A',       // hover CTA
          500: '#A63D3D',       // default CTA
          600: '#8E2C2C',
          700: '#7C1F1F',       // press
          800: '#5E1414',
          900: '#400B0B',
        },
        // Semantic
        success: '#3BA776',
        warning: '#D29A3C',
        danger:  '#B93A3A',
        info:    '#5A82C8',
        // Light palette for PDF (используется в HTML PDF-шаблоне)
        paper: {
          bg:      '#F4F1EA',   // светлый фон брендбука
          surface: '#FFFFFF',
          border:  '#D9D5CC',
          text:    '#15171A',
          muted:   '#6E7480',
        },
      },
      fontFamily: {
        // Заголовки — TT Hoves Pro Bold; запас на случай отсутствия — Graphik/system
        heading: ['"TT Hoves Pro"', 'Graphik', '-apple-system', 'Segoe UI', 'Arial', 'sans-serif'],
        // Основной текст — Graphik
        sans: ['Graphik', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Arial', 'sans-serif'],
      },
      borderRadius: {
        xl: '12px',
        '2xl': '16px',
        '3xl': '20px',
      },
      boxShadow: {
        card: '0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px rgba(0,0,0,0.35)',
        glow: '0 0 0 4px rgba(166,61,61,0.22)',
      },
    },
  },
  plugins: [],
};

export default config;
