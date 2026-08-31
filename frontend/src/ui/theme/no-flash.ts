/**
 * The pre-paint script, as a string the document entry inlines into `<head>`.
 *
 * It runs before first paint, in two independent halves so a failure in one
 * cannot cost the other:
 *
 * 1. Resolve the stored theme preference onto `<html data-theme>`, so there is
 *    no flash of the wrong palette. `"system"` resolves against
 *    `prefers-color-scheme`; anything unrecognized falls back to phosphor.
 * 2. Rebuild the operator's accent overrides into a `<style>` element, for the
 *    same reason: they live in localStorage, so without this the shipped accents
 *    paint first and the chosen ones arrive a frame later. The element carries
 *    the id `accent-overrides.ts` adopts, so the two never append competing
 *    sheets — and the store only rewrites it on an edit, which is why this half
 *    has to emit **both** axes rather than leaving the session signatures for
 *    the bundle to add.
 *
 * `data-mode` is deliberately *not* set here. Which kind of thread is open is
 * chat state rather than a preference, so there is nothing on disk to resolve
 * and nothing to flash; the shell stamps it once the mode is known.
 *
 * The accent half validates before it concatenates. Every key must be a known
 * accent token or session mode and every value a six-digit hex — this is
 * localStorage, which is user-writable, being spliced into a stylesheet, so the
 * guard is what stops a crafted value from closing the rule and opening its own.
 *
 * **It duplicates `serializeOverrides` and cannot import it** — it runs before
 * the bundle exists. `no-flash.test.ts` is what keeps the two from drifting: it
 * executes this string against stubbed globals and asserts the CSS it builds is
 * character-for-character what the store would have written.
 */
export const NO_FLASH_SCRIPT = `(function(){try{var t=localStorage.getItem("odysseus:theme");var s=window.matchMedia&&window.matchMedia("(prefers-color-scheme: light)").matches?"paper":"phosphor";document.documentElement.dataset.theme=(t==="paper"||t==="phosphor")?t:(t==="system"?s:"phosphor");}catch(e){document.documentElement.dataset.theme="phosphor";}try{var a=JSON.parse(localStorage.getItem("odysseus:accents")||"{}"),K=/^accent(-(nominal|warn|alert|info))?$/,V=/^#[0-9a-f]{6}$/i,M=["phosphor","paper"],css="";M.forEach(function(m){var o=a&&a[m];if(!o||typeof o!=="object")return;var d="";Object.keys(o).forEach(function(k){if(K.test(k)&&typeof o[k]==="string"&&V.test(o[k]))d+="--"+k+":"+o[k]+";";});if(d)css+='html[data-theme="'+m+'"]{'+d+"}";});M.forEach(function(m){var o=a&&a.sessionAccent&&a.sessionAccent[m];if(!o||typeof o!=="object")return;["research","code"].forEach(function(x){var v=o[x];if(typeof v==="string"&&V.test(v))css+='html[data-theme="'+m+'"][data-mode="'+x+'"]{--accent:'+v+';}';});});if(css){var el=document.createElement("style");el.id="ody-accent-overrides";el.textContent=css;document.head.appendChild(el);}}catch(e){}})();`;
