// Style registry. A new style is a folder with the same shape as default/.
import { style as defaultStyle } from "./default";
import type { Style } from "./types";

export const STYLES: Record<string, Style> = { default: defaultStyle };
