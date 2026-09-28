//
// Types for `lint-styles.mjs`, imported by its tests.
//

export interface StyleViolation {
  file: string;
  line: number;
  rule:
    | "colour-literal"
    | "arbitrary-value"
    | "palette-class"
    | "static-style"
    | "style-block"
    | "important";
  text: string;
  hint: string;
}

export const ARBITRARY_ALLOWLIST: Set<string>;

export function lintSource(file: string, text: string): StyleViolation[];
