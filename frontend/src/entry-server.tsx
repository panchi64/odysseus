// @refresh reload
import { createHandler, StartServer } from "@solidjs/start/server";

// Runs before first paint, in two independent halves so a failure in one cannot
// cost the other.
//
// 1. Resolve the stored preference onto <html data-theme> so there is no flash
//    of the wrong palette on load. "system" resolves against
//    prefers-color-scheme; anything unrecognized falls back to phosphor.
// 2. Rebuild the operator's accent overrides into a <style> element, for the
//    same reason: they live in localStorage, so without this the shipped accents
//    paint first and the chosen ones arrive a frame later. The element carries
//    the id `accent-store.ts` adopts, so the two never append competing sheets.
//
// The accent half validates before it concatenates. Every key must be a known
// accent token and every value a six-digit hex — this is localStorage, which is
// user-writable, being spliced into a stylesheet, so the guard is what stops a
// crafted value from closing the rule and opening its own.
const NO_FLASH_THEME = `(function(){try{var t=localStorage.getItem("odysseus:theme");var s=window.matchMedia&&window.matchMedia("(prefers-color-scheme: light)").matches?"paper":"phosphor";document.documentElement.dataset.theme=(t==="paper"||t==="phosphor")?t:(t==="system"?s:"phosphor");}catch(e){document.documentElement.dataset.theme="phosphor";}try{var a=JSON.parse(localStorage.getItem("odysseus:accents")||"{}"),K=/^accent(-(nominal|warn|alert|info))?$/,V=/^#[0-9a-f]{6}$/i,css="";["phosphor","paper"].forEach(function(m){var o=a&&a[m];if(!o||typeof o!=="object")return;var d="";Object.keys(o).forEach(function(k){if(K.test(k)&&typeof o[k]==="string"&&V.test(o[k]))d+="--"+k+":"+o[k]+";";});if(d)css+='html[data-theme="'+m+'"]{'+d+"}";});if(css){var el=document.createElement("style");el.id="ody-accent-overrides";el.textContent=css;document.head.appendChild(el);}}catch(e){}})();`;

export default createHandler(() => (
  <StartServer
    document={({ assets, children, scripts }) => (
      <html lang="en" data-theme="phosphor">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>Odysseus</title>
          <link rel="icon" href="/favicon.ico" sizes="32x32" />
          <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
          <script innerHTML={NO_FLASH_THEME} />
          {assets}
        </head>
        <body>
          <div id="app">{children}</div>
          {scripts}
        </body>
      </html>
    )}
  />
));
