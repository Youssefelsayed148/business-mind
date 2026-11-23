import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#0F172A",
        muted: "#64748B",
        line: "#E2E8F0",
        panel: "#F8FAFC",
        accent: "#10B981",
        accentHover: "#059669",
        teal: "#14B8A6",
        mint: "#ECFDF5",
        warn: "#F59E0B",
        danger: "#EF4444",
        info: "#3B82F6",
        sidebar: "#0F172A",
      },
    },
  },
  plugins: [],
};

export default config;
