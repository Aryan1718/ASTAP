import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: "#cbb7fb",
          50: "#f5f1ff",
          100: "#ebe4fe",
          200: "#ddcefd",
          300: "#cbb7fb",
          400: "#b295f2",
          500: "#9975e1",
          600: "#714cb6",
          700: "#5c3f92",
          800: "#4a3274",
          900: "#33234f",
        },
        ink: "#292827",
        muted: "rgba(41, 40, 39, 0.72)",
        line: "#dcd7d3",
        canvas: "#ffffff",
        panel: "#ffffff",
        hero: "#1b1938",
        cream: "#e9e5dd",
        link: "#714cb6",
      },
      fontFamily: {
        sans: ['"Super Sans VF"', "system-ui", "-apple-system", '"Segoe UI"', "Roboto", "sans-serif"],
        display: ['"Super Sans VF"', "system-ui", "-apple-system", '"Segoe UI"', "Roboto", "sans-serif"],
      },
      boxShadow: {
        panel: "0 20px 50px rgba(27, 25, 56, 0.06)",
        soft: "0 10px 25px rgba(27, 25, 56, 0.04)",
      },
      backgroundImage: {
        "hero-gradient":
          "radial-gradient(circle at top left, rgba(203, 183, 251, 0.22), transparent 30%), linear-gradient(180deg, #1b1938 0%, #241f4e 52%, #2d275c 100%)",
      },
    },
  },
  plugins: [],
};

export default config;
