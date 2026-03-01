import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: "#E09A19",
          50: "#FFF8EA",
          100: "#FCEFD0",
          200: "#F6DCA0",
          300: "#F0C56C",
          400: "#E8AF3D",
          500: "#E09A19",
          600: "#BF7C12",
          700: "#925C10",
          800: "#64400D",
          900: "#382306",
        },
        ink: "#101828",
        muted: "#667085",
        line: "#E7E1D7",
        canvas: "#FCFBF8",
        panel: "#FFFDF8",
      },
      fontFamily: {
        sans: ['"Avenir Next"', '"Helvetica Neue"', "sans-serif"],
        display: ['"Iowan Old Style"', '"Palatino Linotype"', "serif"],
      },
      boxShadow: {
        panel: "0 18px 45px rgba(16, 24, 40, 0.07)",
        soft: "0 10px 30px rgba(16, 24, 40, 0.05)",
      },
      backgroundImage: {
        "hero-grid":
          "linear-gradient(rgba(224,154,25,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(224,154,25,0.06) 1px, transparent 1px)",
      },
    },
  },
  plugins: [],
};

export default config;
