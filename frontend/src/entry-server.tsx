// @refresh reload
import { createHandler, StartServer } from "@solidjs/start/server";

// Runs before first paint: reflect the stored theme onto <html data-theme>
// so there is no flash of the wrong palette on load. Defaults to phosphor.
const NO_FLASH_THEME = `(function(){try{var t=localStorage.getItem("odysseus:theme");document.documentElement.dataset.theme=(t==="paper"||t==="phosphor")?t:"phosphor";}catch(e){document.documentElement.dataset.theme="phosphor";}})();`;

export default createHandler(() => (
  <StartServer
    document={({ assets, children, scripts }) => (
      <html lang="en" data-theme="phosphor">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>ODYSSEUS</title>
          <link rel="icon" href="/favicon.ico" />
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
