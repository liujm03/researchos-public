interface FormulaNode {
  type: string;
  children?: FormulaNode[];
  value?: string;
  lang?: string | null;
  data?: Record<string, unknown>;
}

const greek: Record<string, string> = {
  α: "alpha",
  β: "beta",
  γ: "gamma",
  δ: "delta",
  ε: "epsilon",
  η: "eta",
  θ: "theta",
  λ: "lambda",
  μ: "mu",
  ν: "nu",
  π: "pi",
  ρ: "rho",
  σ: "sigma",
  τ: "tau",
  φ: "phi",
  ψ: "psi",
  ω: "omega",
  Γ: "Gamma",
  Δ: "Delta",
  Θ: "Theta",
  Λ: "Lambda",
  Σ: "Sigma",
  Ω: "Omega",
};
const subscripts: Record<string, string> = {
  "₀": "0",
  "₁": "1",
  "₂": "2",
  "₃": "3",
  "₄": "4",
  "₅": "5",
  "₆": "6",
  "₇": "7",
  "₈": "8",
  "₉": "9",
  ₜ: "t",
  ₙ: "n",
  ᵢ: "i",
};

/** A deliberately small display-only syntax adapter, not an equation repairer. */
function legacyExpression(source: string): string | null {
  if (!/[=~]/.test(source) || !/[αβγηλσμθπΔΣₜ₀₁₂₃₄₅₆₇₈₉]/.test(source))
    return null;
  let output = "";
  for (let index = 0; index < source.length;) {
    const char = source[index];
    if (greek[char]) {
      output += `\\${greek[char]} `;
      index++;
    } else if (subscripts[char]) {
      let sub = "";
      while (subscripts[source[index]]) sub += subscripts[source[index++]];
      output += `_{${sub}}`;
    } else if (char === "_") {
      const match = /^[A-Za-z0-9]+/.exec(source.slice(index + 1));
      if (!match) return null;
      output +=
        match[0].length > 1 ? `_{\\mathrm{${match[0]}}}` : `_{${match[0]}}`;
      index += match[0].length + 1;
    } else if (char === "^") {
      const match = /^(?:\(([A-Za-z0-9+\-− ]+)\)|([A-Za-z0-9]))/.exec(
        source.slice(index + 1),
      );
      if (!match) return null;
      output += `^{${(match[1] ?? match[2]).replaceAll("−", "-")}}`;
      index += match[0].length + 1;
    } else if (/[A-Za-z]/.test(char)) {
      const word = /^[A-Za-z]+/.exec(source.slice(index))![0];
      output +=
        word === "exp"
          ? "\\exp "
          : word.length > 1
            ? `\\operatorname{${word}}`
            : word;
      index += word.length;
    } else if (char === "′" || char === "’" || char === "'") {
      output += "^{\\prime}";
      index++;
    } else if (char === "~") {
      output += "\\sim ";
      index++;
    } else if (char === "×") {
      output += "\\times ";
      index++;
    } else if (char === "−") {
      output += "-";
      index++;
    } else if (char === "，") {
      output += "\\qquad ";
      index++;
    } else if (/[0-9\s+\-=()[\]/!.,]/.test(char)) {
      output += char;
      index++;
    } else return null;
  }
  // Only atomic divisions have an unambiguous boundary (e.g. 2R/c or β^(K+1)/K!).
  // Keep all other slashes unchanged rather than guessing a numerator's extent.
  const atom = String.raw`(?:\\(?:${Object.values(greek).join("|")})\s*|\d+[A-Za-z]?|[A-Za-z])(?:\^\{[^{}]+\})?`;
  return output.replace(
    new RegExp(`(${atom})\\s*/\\s*([A-Za-z]!?)`, "g"),
    (_whole, numerator: string, denominator: string) =>
      `\\frac{${numerator}}{${denominator}}`,
  );
}

function codeMath(value: string, language?: string | null): string[] | null {
  if (value.length > 12000) return null;
  if (["math", "latex", "tex"].includes(language ?? "")) {
    // Math fences carry explicit user intent; KaTeX remains bounded and untrusted.
    return [value.replace(/^\s*\$\$\s*\n?/, "").replace(/\n?\s*\$\$\s*$/, "")];
  }
  if (language && language !== "text" && language !== "plaintext") return null;
  const lines = value.split(/\r?\n/).filter((line) => line.trim());
  if (lines.length === 0 || lines.length > 20) return null;
  const equations: string[] = [];
  for (const line of lines) {
    const numbered = /\s{2,}\((\d{1,4})\)\s*$/.exec(line);
    const expression = legacyExpression(
      numbered ? line.slice(0, numbered.index) : line,
    );
    if (!expression) return null; // Never partly reinterpret prose/code.
    equations.push(expression + (numbered ? `\\tag{${numbered[1]}}` : ""));
  }
  return equations;
}

/** Runs after remark-math. Only recognized code nodes change in the preview AST. */
export function remarkFormulaCompat() {
  return (tree: FormulaNode) => {
    function walk(parent: FormulaNode) {
      const children = parent.children;
      if (!children) return;
      for (let index = 0; index < children.length; index++) {
        const node = children[index];
        if (node.type === "code" && typeof node.value === "string") {
          const equations = codeMath(node.value, node.lang);
          if (equations) {
            const nodes = equations.map((value) => ({
              type: "math" as const,
              value,
              data: {
                hName: "div",
                hProperties: { className: ["math", "math-display"] },
                hChildren: [{ type: "text" as const, value }],
              },
            }));
            children.splice(index, 1, ...nodes);
            index += nodes.length - 1;
          }
        } else if (node.children) {
          walk(node);
        }
      }
    }
    walk(tree);
  };
}
