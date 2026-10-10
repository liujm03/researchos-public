import { globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

const config = [
  ...nextVitals,
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts", "public/pdfjs/**"]),
];

export default config;
