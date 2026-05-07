import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        blue: {
          600: '#0066FF',
          700: '#0055D4',
          900: '#003A9B',
        },
        green: {
          500: '#34C759',
        },
        red: {
          500: '#FF3B30',
        },
        orange: {
          500: '#FF9500',
        },
        gray: {
          50: '#F9F9FB',
          100: '#F2F2F7',
          200: '#E5E5EA',
          400: '#C7C7CC',
          500: '#8E8E93',
          900: '#1C1C1E',
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Arial', 'sans-serif'],
      },
      borderRadius: {
        xl: '12px',
        '2xl': '16px',
        '3xl': '20px',
      },
    },
  },
  plugins: [],
};

export default config;
