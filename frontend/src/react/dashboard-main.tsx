/** React mount points for index.html (the vanilla dashboard).
 *
 *  Each migration stage mounts its component(s) into an existing DOM
 *  container id from index.html (Stage 1: #dashboard-react-root, added for
 *  the Project Manager overlay) or directly into an already-empty container
 *  the vanilla markup already had (Stage 2: #list-rows, #results-tbody,
 *  #scope-banner — no index.html edits needed for these, they were empty
 *  `<div>`/`<tbody>` placeholders the vanilla renderer used to fill via
 *  innerHTML). Styled by the existing tokens.css/components.css/app.css —
 *  intentionally NOT importing the React app's Tailwind index.css here, so
 *  migrated features keep the current, unchanged visual identity instead of
 *  pulling in a second competing design-token system before that
 *  unification is explicitly decided.
 *
 *  Bridge to the still-vanilla dashboard: React and vanilla code communicate
 *  only through the shared store.js singleton (mutations + its pub/sub) or,
 *  for features with no natural shared-state hook (like opening a modal),
 *  plain window CustomEvents — never direct imports across the boundary.
 *  This is what lets each stage move independently without the others
 *  needing to change. See ProjectManager.tsx and useStoreVersion.ts for the
 *  two concrete patterns. */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { WizardBanner, WizardCards, WizardLog, WizardRail } from "./features/benchmark-wizard/Wizard";
import { Chat } from "./features/chat/Chat";
import { ElementList } from "./features/element-review/ElementList";
import { ResultsTable } from "./features/element-review/ResultsTable";
import { ScopeBanner } from "./features/element-review/ScopeBanner";
import { CountConsistency, Inspector } from "./features/inspector/Inspector";
import { ReviewWorkspace } from "./features/inspector/ReviewWorkspace";
import { RunsComparison } from "./features/inspector/RunsComparison";
import { ProjectManager } from "./features/project-manager/ProjectManager";

function mount(id: string, node: React.ReactNode) {
  const container = document.getElementById(id);
  if (!container) return;
  createRoot(container).render(<StrictMode>{node}</StrictMode>);
}

mount("dashboard-react-root", <ProjectManager />);
mount("list-rows", <ElementList />);
mount("results-tbody", <ResultsTable />);
mount("scope-banner", <ScopeBanner />);
mount("chat-log", <Chat />);
mount("insp-body", <Inspector />);
mount("cc-table", <CountConsistency />);
mount("runs-body", <RunsComparison />);
mount("rev-body", <ReviewWorkspace />);
mount("bm-rail", <WizardRail />);
mount("bm-cards", <WizardCards />);
mount("bm-log", <WizardLog />);
mount("wizard-banner-root", <WizardBanner />);
