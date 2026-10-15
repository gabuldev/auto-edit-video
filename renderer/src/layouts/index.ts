// Layout registry. A new layout is a folder with the same shape as default/.
import { layout as defaultLayout } from "./default";
import type { Layout } from "./types";

export const LAYOUTS: Record<string, Layout> = { default: defaultLayout };
