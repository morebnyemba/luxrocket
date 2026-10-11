/*! LUX ROCKET embed SDK v1 — framework-free, no dependencies (doc 11 §3, §5). */
(function (global) {
  "use strict";

  /**
   * Mount the game.
   * @param {object} opts
   * @param {HTMLElement} opts.container  element to render the iframe into
   * @param {string} opts.iframeUrl       `iframe_url` from POST /operator/v1/sessions (no token)
   * @param {string} opts.launchToken     one-time `launch_token` from the same response
   * @param {function} [opts.onEvent]     called with every message from the game
   * @param {function} [opts.onRelaunchRequired] fetch a new token from your backend and call relaunch(token)
   */
  function mount(opts) {
    if (!opts || !opts.container || !opts.iframeUrl || !opts.launchToken) {
      throw new Error("LuxRocket.mount: container, iframeUrl and launchToken are required");
    }
    var gameOrigin = new URL(opts.iframeUrl).origin;
    var token = opts.launchToken;
    var iframe = document.createElement("iframe");
    iframe.src = opts.iframeUrl;
    iframe.title = "LUX ROCKET";
    iframe.allow = "fullscreen; autoplay";
    iframe.setAttribute("sandbox", "allow-scripts allow-same-origin");
    iframe.referrerPolicy = "origin";
    iframe.style.cssText = "width:100%;height:100%;border:0;display:block";
    opts.container.appendChild(iframe);

    function onMessage(event) {
      // Exact origin and source identity (doc 11 §5).
      if (event.origin !== gameOrigin || event.source !== iframe.contentWindow) return;
      var msg = event.data;
      if (!msg || msg.lr !== 1 || typeof msg.type !== "string") return;
      if (msg.type === "LR_READY" && token) {
        iframe.contentWindow.postMessage(
          { lr: 1, type: "LR_LAUNCH", nonce: msg.nonce, data: { launch_token: token } },
          gameOrigin
        );
        token = null; // single use
      } else if (msg.type === "LR_RELAUNCH_REQUIRED" && typeof opts.onRelaunchRequired === "function") {
        opts.onRelaunchRequired(msg.data || {});
      } else if (msg.type === "LR_FULLSCREEN_REQUEST") {
        if (iframe.requestFullscreen) iframe.requestFullscreen().catch(function () {});
      }
      if (typeof opts.onEvent === "function") opts.onEvent(msg);
    }

    global.addEventListener("message", onMessage);

    return {
      iframe: iframe,
      /** Load a fresh session (after LR_RELAUNCH_REQUIRED). */
      relaunch: function (iframeUrl, launchToken) {
        token = launchToken;
        iframe.src = iframeUrl;
      },
      setAudio: function (muted) {
        iframe.contentWindow.postMessage({ lr: 1, type: "LR_SET_AUDIO", data: { muted: !!muted } }, gameOrigin);
      },
      destroy: function () {
        global.removeEventListener("message", onMessage);
        iframe.remove();
      },
    };
  }

  global.LuxRocket = { version: "1", mount: mount };
})(typeof window !== "undefined" ? window : this);
