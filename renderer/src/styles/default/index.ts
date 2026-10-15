import type { Style } from "../types";
import { cta } from "./Cta";
import { lowerThird } from "./LowerThird";

export const style: Style = {
  label: "Padrão",
  fonts: { Bold: "Montserrat-ExtraBold.ttf", Semi: "Montserrat-SemiBold.ttf" },
  overlays: { lower_third: lowerThird, cta },
};
