import type { Config } from "tailwindcss";

// Palette lifted from the "Meridian" reference: near-black green-tinted ground, teal accent,
// emerald positives, amber warnings. The momentum 5-scale is the one place these hues carry
// semantic meaning (doc 10 §2 — "color always means momentum").
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0A0E0F",
        surface: "#0F1618",
        card: "#121A1C",
        "card-hover": "#16211F",
        border: "#1E2A2C",
        "border-soft": "#182123",
        accent: "#2DD4BF",
        "accent-dim": "#1B9C8E",
        cyan: "#22D3EE",
        positive: "#34D399",
        warn: "#F59E0B",
        purple: "#A78BFA",
        pink: "#F472B6",
        text: "#E6EDEE",
        muted: "#7C8B8E",
        faint: "#55686B",
        // momentum states
        dormant: "#64748B",
        simmering: "#38BDF8",
        accelerating: "#2DD4BF",
        breakout: "#34D399",
        fading: "#F59E0B",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.02) inset, 0 8px 30px -12px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};

export default config;
