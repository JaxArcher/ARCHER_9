/**
 * ARCHER browser client — TERMINAL renderer (Phase 6, Spec Section 9).
 * Real interactive PowerShell session in the Artifacts tab powered by xterm.js + pywinpty.
 * Shared between Col (direct keyboard typing) and ARCHER (visible [ARCHER] runs).
 */
(() => {
  const terminalPane = document.getElementById("tab-terminal");
  const container = document.getElementById("archer-terminal-container");
  if (!terminalPane || !container) return;

  let term = null;
  let fitAddon = null;
  let isInitialized = false;

  function initTerminal() {
    if (isInitialized) return;
    if (typeof Terminal === "undefined") {
      console.warn("[Terminal] xterm.js not loaded yet, retrying...");
      setTimeout(initTerminal, 100);
      return;
    }

    term = new Terminal({
      cursorBlink: true,
      cursorStyle: "block",
      fontFamily: "Consolas, 'Courier New', monospace",
      fontSize: 13,
      lineHeight: 1.25,
      scrollback: 5000,
      theme: {
        background: "#040a12",
        foreground: "#c9f6ff",
        cursor: "#53e8ff",
        cursorAccent: "#040a12",
        selectionBackground: "rgba(83, 232, 255, 0.3)",
        black: "#040a12",
        red: "#ff7675",
        green: "#2ecc71",
        yellow: "#f1c40f",
        blue: "#3498db",
        magenta: "#9b59b6",
        cyan: "#53e8ff",
        white: "#d8f5ff",
        brightBlack: "#57606f",
        brightRed: "#ff6b6b",
        brightGreen: "#1dd1a1",
        brightYellow: "#feca57",
        brightBlue: "#54a0ff",
        brightMagenta: "#ff9ff3",
        brightCyan: "#48dbfb",
        brightWhite: "#ffffff",
      },
    });

    if (typeof FitAddon !== "undefined" && FitAddon.FitAddon) {
      fitAddon = new FitAddon.FitAddon();
      term.loadAddon(fitAddon);
    }

    term.open(container);

    if (fitAddon) {
      try {
        fitAddon.fit();
      } catch (e) {
        // Ignored on initial hidden mount
      }
    }

    // Forward keystrokes to server
    term.onData((data) => {
      if (window.ArcherClient && window.ArcherClient.sendTerminalInput) {
        window.ArcherClient.sendTerminalInput(data);
      }
    });

    // Forward dimension resize to server
    term.onResize((size) => {
      if (window.ArcherClient && window.ArcherClient.sendTerminalResize) {
        window.ArcherClient.sendTerminalResize(size.cols, size.rows);
      }
    });

    // Wire Clear and Restart buttons
    const clearBtn = document.getElementById("terminal-btn-clear");
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        if (term) term.clear();
      });
    }

    const restartBtn = document.getElementById("terminal-btn-restart");
    if (restartBtn) {
      restartBtn.addEventListener("click", () => {
        if (window.ArcherClient && window.ArcherClient.sendTerminalRestart) {
          window.ArcherClient.sendTerminalRestart();
        }
      });
    }

    // Wire WebSocket events
    if (window.ArcherClient) {
      window.ArcherClient.on("terminalOutput", (chunk) => {
        if (term && chunk) term.write(chunk);
      });

      window.ArcherClient.on("terminalHistory", (history) => {
        if (term && history) {
          term.write(history);
        }
      });

      window.ArcherClient.on("terminalRestarted", () => {
        if (term) {
          term.clear();
          term.writeln("\r\n\x1b[33m--- PowerShell session restarted ---\x1b[0m\r\n");
          if (fitAddon) fitAddon.fit();
        }
      });

      window.ArcherClient.on("connected", () => {
        if (window.ArcherClient.sendTerminalGetHistory) {
          window.ArcherClient.sendTerminalGetHistory();
        }
      });
    }

    // ResizeObserver on container to reflow xterm cleanly
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(() => {
        if (fitAddon && container.offsetWidth > 50 && container.offsetHeight > 50) {
          try {
            fitAddon.fit();
          } catch (e) {
            // Container may be hidden
          }
        }
      });
      ro.observe(container);
    }

    isInitialized = true;

    // Fetch initial history if connected
    if (window.ArcherClient && window.ArcherClient.sendTerminalGetHistory) {
      window.ArcherClient.sendTerminalGetHistory();
    }
  }

  // Reflow and fit terminal when switching to ARTIFACTS tab
  window.addEventListener("archer-tab-changed", (evt) => {
    if (evt.detail && evt.detail.activeTab === "artifacts") {
      setTimeout(() => {
        if (!isInitialized) {
          initTerminal();
        } else if (fitAddon) {
          try {
            fitAddon.fit();
          } catch (e) {
            // Container not ready
          }
        }
      }, 60);
    }
  });

  // Init on DOM load
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initTerminal);
  } else {
    setTimeout(initTerminal, 50);
  }
})();
