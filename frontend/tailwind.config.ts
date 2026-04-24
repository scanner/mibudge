//
// Tailwind CSS configuration for mibudge.
//
// Design tokens mirror the palette in docs/UI_SPEC.md §2.2.  Semantic
// state mappings (funded / progress / warn / over / paused) use the
// colour tokens below via utility classes rather than named aliases so
// that the mapping stays visible at the call site.
//

import type { Config } from "tailwindcss";
import forms from "@tailwindcss/forms";

const config: Config = {
  content: ["./index.html", "./src/**/*.{vue,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ocean: {
          50: "#EAF4FF",
          400: "#378ADD",
          600: "#185FA5",
          800: "#0C447C",
        },
        mint: {
          50: "#E1F5EE",
          400: "#1D9E75",
          600: "#0F6E56",
          800: "#085041",
        },
        amber: {
          50: "#FFF5E6",
          400: "#EF9F27",
          600: "#854F0B",
        },
        coral: {
          50: "#FCEBEB",
          400: "#E24B4A",
          600: "#A32D2D",
        },
        neutral: {
          50: "#F5F4F0",
          100: "#F1EFE8",
          200: "#E0DED8",
          300: "#D3D1C7",
          400: "#B4B2A9",
          500: "#888780",
          600: "#5F5E5A",
          700: "#444441",
          900: "#1a1a1a",
        },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      borderRadius: {
        card: "14px",
        subcard: "10px",
      },
    },
  },
  plugins: [forms],
};

export default config;
