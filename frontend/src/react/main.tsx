import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

/* One font-loading path for the whole product. This page declared its own
   @fontsource imports (400/500/600 sans + 400 mono) while the dashboard loads
   a different set through src/fonts.js, so the two pages could render the same
   text in different weights. fonts.js is the single source; it also carries
   the display face the dashboard uses, so the pages can no longer drift. */
import "../fonts.js";

import App from "@/App";
import "@/index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
