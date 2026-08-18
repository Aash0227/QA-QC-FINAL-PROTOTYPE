/* panels/chat.js — compatibility shim (frontend migration).
   The chat drawer is now rendered by src/react/features/chat/Chat.tsx,
   mounted directly into the existing #chat-log container.

   initChat() stays exported here because panels/inspector.js's still-vanilla
   drawer manager imports and calls it by name on first open (openDrawer()).
   It dispatches a window event instead of importing React code directly —
   the same bridge pattern used for the Project Manager (Stage 1). */

export function initChat() {
  window.dispatchEvent(new CustomEvent("chat-init"));
}
