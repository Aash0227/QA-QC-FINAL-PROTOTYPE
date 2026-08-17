/* fonts.js — self-hosted @font-face rules, bundled by Vite.

   These are the same three families and weights the Google Fonts <link> used
   to fetch; vendoring them is what lets the app start with the network off,
   which docs/DEPLOY.md requires of everything except chat.

   Latin subset only (the UI is English), and only the weights tokens.css
   actually declares: --font-display 600/800, --font-body and --font-mono
   400/600. Adding a weight here that no rule uses only grows the bundle.

   Imported from JS rather than @import-ed in tokens.css because Vite's postcss
   pass does not resolve bare package specifiers in CSS.

   The specifiers are deliberately extensionless. Every @fontsource package maps
   "./*" -> "./*.css" in its exports, but only the newer builds also map
   "./*.css"; big-shoulders-display does not, so the ".css" form fails to
   resolve for that one package. Extensionless works for all three. */

import "@fontsource/big-shoulders-display/latin-600";
import "@fontsource/big-shoulders-display/latin-800";
import "@fontsource/ibm-plex-sans/latin-400";
import "@fontsource/ibm-plex-sans/latin-600";
import "@fontsource/ibm-plex-mono/latin-400";
import "@fontsource/ibm-plex-mono/latin-600";
