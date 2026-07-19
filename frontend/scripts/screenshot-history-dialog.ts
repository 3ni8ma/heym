import { chromium } from "@playwright/test";
import { resolve } from "node:path";

const MOBILE_VIEWPORT = { width: 375, height: 667 };
const ARTIFACTS = resolve(import.meta.dirname, "..", ".e2e-artifacts");

const HTML = `<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dialog Mobile Preview</title>
<style>
  :root {
    --background: 0 0% 3.9%;
    --foreground: 0 0% 98%;
    --card: 0 0% 6.9%;
    --card-foreground: 0 0% 98%;
    --popover: 0 0% 3.9%;
    --popover-foreground: 0 0% 98%;
    --primary: 252 96% 74%;
    --primary-foreground: 0 0% 100%;
    --secondary: 0 0% 14.9%;
    --secondary-foreground: 0 0% 98%;
    --muted: 0 0% 14.9%;
    --muted-foreground: 0 0% 63.9%;
    --accent: 0 0% 14.9%;
    --accent-foreground: 0 0% 98%;
    --border: 0 0% 14.9%;
    --ring: 252 96% 74%;
    --radius: 0.75rem;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: hsl(var(--background));
    color: hsl(var(--foreground));
    font-size: 14px;
    line-height: 1.5;
  }
  .fixed { position: fixed; }
  .inset-0 { inset: 0; }
  .z-50 { z-index: 50; }
  .bg-card { background: hsl(var(--card)); }
  .border { border-width: 1px; }
  .border-border\\/60 { border-color: hsl(var(--border) / 0.6); }
  .rounded-2xl { border-radius: 1rem; }
  .flex { display: flex; }
  .flex-col { flex-direction: column; }
  .items-center { align-items: center; }
  .items-start { align-items: flex-start; }
  .justify-center { justify-content: center; }
  .justify-between { justify-content: space-between; }
  .justify-end { justify-content: flex-end; }
  .flex-1 { flex: 1 1 0%; }
  .flex-shrink-0 { flex-shrink: 0; }
  .shrink-0 { flex-shrink: 0; }
  .flex-wrap { flex-wrap: wrap; }
  .min-w-0 { min-width: 0; }
  .min-h-0 { min-height: 0; }
  .overflow-hidden { overflow: hidden; }
  .overflow-y-auto { overflow-y: auto; }
  .truncate {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .whitespace-pre-wrap { white-space: pre-wrap; }
  .break-all { word-break: break-all; }
  .w-full { width: 100%; }
  .w-3 { width: 0.75rem; }
  .w-3\\.5 { width: 0.875rem; }
  .w-4 { width: 1rem; }
  .w-5 { width: 1.25rem; }
  .h-3 { height: 0.75rem; }
  .h-3\\.5 { height: 0.875rem; }
  .h-4 { height: 1rem; }
  .h-5 { height: 1.25rem; }
  .w-px { width: 1px; }
  .h-6 { height: 1.5rem; }
  .h-8 { height: 2rem; }
  .w-8 { width: 2rem; }
  .p-2 { padding: 0.5rem; }
  .p-2\\.5 { padding: 0.625rem; }
  .p-3 { padding: 0.75rem; }
  .p-4 { padding: 1rem; }
  .px-1 { padding-left: 0.25rem; padding-right: 0.25rem; }
  .px-1\\.5 { padding-left: 0.375rem; padding-right: 0.375rem; }
  .px-2 { padding-left: 0.5rem; padding-right: 0.5rem; }
  .px-3 { padding-left: 0.75rem; padding-right: 0.75rem; }
  .py-0 { padding-top: 0; padding-bottom: 0; }
  .py-0\\.5 { padding-top: 0.125rem; padding-bottom: 0.125rem; }
  .pb-3 { padding-bottom: 0.75rem; }
  .mb-3 { margin-bottom: 0.75rem; }
  .mt-0\\.5 { margin-top: 0.125rem; }
  .mt-1 { margin-top: 0.25rem; }
  .ml-auto { margin-left: auto; }
  .gap-0\\.5 { gap: 0.125rem; }
  .gap-1 { gap: 0.25rem; }
  .gap-1\\.5 { gap: 0.375rem; }
  .gap-2 { gap: 0.5rem; }
  .gap-3 { gap: 0.75rem; }
  .space-y-1 > * + * { margin-top: 0.25rem; }
  .space-y-2 > * + * { margin-top: 0.5rem; }
  .gap-x-2 { column-gap: 0.5rem; }
  .gap-y-1\\.5 { row-gap: 0.375rem; }
  .text-xs { font-size: 0.75rem; line-height: 1rem; }
  .text-sm { font-size: 0.875rem; line-height: 1.25rem; }
  .text-base { font-size: 1rem; line-height: 1.5rem; }
  .font-medium { font-weight: 500; }
  .font-semibold { font-weight: 600; }
  .tracking-tight { letter-spacing: -0.025em; }
  .text-muted-foreground { color: hsl(var(--muted-foreground)); }
  .text-primary { color: hsl(var(--primary)); }
  .text-emerald-500 { color: #10b981; }
  .text-red-500 { color: #ef4444; }
  .text-amber-500 { color: #f59e0b; }
  .text-blue-400 { color: #60a5fa; }
  .text-violet-400 { color: #a78bfa; }
  .text-gray-400 { color: #9ca3af; }
  .bg-muted\\/20 { background: hsl(var(--muted) / 0.2); }
  .bg-muted\\/30 { background: hsl(var(--muted) / 0.3); }
  .bg-muted\\/10 { background: hsl(var(--muted) / 0.1); }
  .bg-primary\\/10 { background: hsl(var(--primary) / 0.1); }
  .bg-amber-500\\/10 { background: rgba(245, 158, 11, 0.1); }
  .bg-blue-500\\/10 { background: rgba(59, 130, 246, 0.1); }
  .bg-red-500\\/10 { background: rgba(239, 68, 68, 0.1); }
  .bg-violet-500\\/15 { background: rgba(139, 92, 246, 0.15); }
  .bg-gray-500\\/20 { background: rgba(107, 114, 128, 0.2); }
  .bg-amber-500\\/20 { background: rgba(245, 158, 11, 0.2); }
  .bg-red-500\\/20 { background: rgba(239, 68, 68, 0.2); }
  .bg-violet-500\\/20 { background: rgba(139, 92, 246, 0.2); }
  .bg-emerald-500\\/5 { background: rgba(16, 185, 129, 0.05); }
  .text-amber-400 { color: #fbbf24; }
  .text-amber-600 { color: #d97706; }
  .text-emerald-400 { color: #34d399; }
  .text-red-400 { color: #f87171; }
  .text-violet-400 { color: #a78bfa; }
  .rounded-md { border-radius: 0.375rem; }
  .rounded-lg { border-radius: 0.5rem; }
  .rounded { border-radius: 0.25rem; }
  .border-primary\\/60 { border-color: hsl(var(--primary) / 0.6); }
  .border-border\\/40 { border-color: hsl(var(--border) / 0.4); }
  .border-blue-500\\/30 { border-color: rgba(59, 130, 246, 0.3); }
  .border-emerald-500\\/20 { border-color: rgba(16, 185, 129, 0.2); }
  .hover\\:bg-muted\\/40:hover { background: hsl(var(--muted) / 0.4); }
  .transition-colors { transition: color, background-color 0.15s; }
  .text-left { text-align: left; }
  .text-center { text-align: center; }
  .inline-flex { display: inline-flex; }
  .uppercase { text-transform: uppercase; }
  .pointer-events-none { pointer-events: none; }
  .opacity-50 { opacity: 0.5; }
  .relative { position: relative; }
  .h-px { height: 1px; }
  .bg-border\\/60 { background: hsl(var(--border) / 0.6); }

  button {
    cursor: pointer;
    border: none;
    background: none;
    font: inherit;
    color: inherit;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s;
  }
  button:hover { background: hsl(var(--muted) / 0.3); }
  .btn-sm {
    padding: 0.25rem 0.5rem;
    font-size: 0.75rem;
    height: 1.5rem;
    border-radius: 0.25rem;
  }
  .btn-ghost { background: transparent; }
  .btn-outline { border: 1px solid hsl(var(--border) / 0.6); }
  .btn-destructive { color: #ef4444; background: rgba(239, 68, 68, 0.1); }
  .btn-icon {
    width: 2rem; height: 2rem;
    border-radius: 0.5rem;
    color: hsl(var(--muted-foreground));
  }
  .btn-icon:hover { color: hsl(var(--foreground)); }
  .dialog-backdrop {
    position: fixed; inset: 0;
    background: rgba(0, 0, 0, 0.65);
    backdrop-filter: blur(12px);
  }
  .dialog-content {
    max-width: 100vw;
    max-height: 90vh;
    box-shadow: 0 0 0 1px hsl(var(--border) / 0.5), 0 0 1px rgba(0,0,0,0.0125);
  }
  .dialog-header {
    position: relative;
    padding-bottom: 0.75rem;
    margin-bottom: 0.75rem;
  }
  .dialog-header::after {
    content: '';
    position: absolute;
    bottom: -1px; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent 0%, hsl(var(--border)) 20%, hsl(var(--primary) / 0.4) 50%, hsl(var(--border)) 80%, transparent 100%);
  }

  .max-h-40 { max-height: 10rem; }
  .max-h-32 { max-height: 8rem; }
  .max-h-\\[30vh\\] { max-height: 30vh; }
  .h-\\[75vh\\] { height: 75vh; }

  .pl-5 { padding-left: 1.25rem; }
  .pl-6 { padding-left: 1.5rem; }

  .animate-spin {
    animation: spin 1s linear infinite;
  }
  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
</style>
</head>
<body>
<div class="fixed inset-0 z-50 flex items-center justify-center">
  <div class="dialog-backdrop"></div>
  <div class="dialog-content relative z-50 w-full border border-border/60 bg-card p-4 flex flex-col max-h-[90vh] rounded-2xl max-w-4xl">

    <!-- HEADER -->
    <div class="dialog-header flex items-center justify-between pb-3 mb-3 gap-1.5 shrink-0">
      <div class="flex items-center gap-1.5 min-w-0 flex-1 overflow-hidden">
        <div class="min-w-0">
          <h2 class="text-sm font-semibold tracking-tight" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">Execution History</h2>
        </div>
      </div>
      <div class="flex items-center gap-1 flex-shrink-0">
        <button class="btn-icon flex items-center justify-center h-8 w-8 rounded-lg text-muted-foreground hover:text-foreground">
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
        </button>
      </div>
    </div>

    <!-- TOP BAR -->
    <div class="flex items-start justify-between gap-2 mb-3 shrink-0">
      <div class="flex min-w-0 flex-1 flex-col gap-1.5">
        <p class="text-sm text-muted-foreground flex items-center gap-2 shrink-0">12 run(s)</p>
        <select class="w-full p-2 text-sm rounded-md border border-border/60 bg-muted/20">
          <option>All Tags</option>
          <option>Chat</option>
          <option>Manual</option>
        </select>
      </div>
      <div class="flex items-center gap-0.5 shrink-0 flex-wrap justify-end">
        <button class="btn-sm btn-ghost" title="Refresh">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 2.1a10 10 0 1 0 3.2 5.1"/></svg>
        </button>
        <button class="btn-sm btn-outline" title="Search">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
        </button>
        <button class="btn-sm btn-ghost gap-2" title="Clear history">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14"/></svg>
        </button>
      </div>
    </div>

    <!-- TWO-COLUMN LAYOUT (mobile: stacked) -->
    <div class="flex flex-col gap-3 min-h-0 h-[75vh]">

      <!-- LEFT: run list -->
      <div class="w-full shrink-0 flex flex-col overflow-hidden border-b border-border/40 pb-3 max-h-[30vh]">
        <div class="overflow-y-auto flex-1 space-y-1">

          <!-- Running execution -->
          <div class="p-2 rounded-md border border-blue-500/30 bg-blue-500/10">
            <div class="flex items-center gap-1.5">
              <span class="inline-flex w-3 h-3 text-blue-400 animate-spin">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
              </span>
              <span class="text-xs font-medium text-blue-400">Running</span>
              <button class="btn-sm btn-outline ml-auto" style="font-size:10px;height:1.75rem;min-height:1.75rem;">Open live</button>
            </div>
            <div class="mt-1 flex min-w-0 items-center justify-between gap-2">
              <div class="min-w-0 truncate text-xs text-muted-foreground" style="font-size:10px">7/19/2026, 4:30:23 PM</div>
              <button class="btn-sm btn-destructive" style="font-size:10px;height:1.75rem;min-height:1.75rem;">Cancel</button>
            </div>
          </div>
          <div class="border-t border-border/40 my-1"></div>

          <!-- Run entries -->
          <button class="w-full text-left p-2.5 rounded-md border bg-muted/20 hover:bg-muted/40 transition-colors border-primary/60 bg-primary/10">
            <div class="flex items-center gap-1.5 min-w-0">
              <span class="inline-flex w-3.5 h-3.5 shrink-0" style="color:#10b981">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>
              </span>
              <span class="text-xs font-medium truncate flex-1">7/19/2026, 4:25:10 PM</span>
            </div>
            <div class="flex items-center gap-1.5 mt-0.5 pl-5">
              <span class="text-xs text-muted-foreground" style="font-size:10px">245.32ms</span>
              <span class="px-1 py-0 rounded uppercase text-violet-400 bg-violet-500/20" style="font-size:9px;font-weight:600">Chat</span>
            </div>
          </button>
          <button class="w-full text-left p-2.5 rounded-md border bg-muted/20 hover:bg-muted/40 transition-colors">
            <div class="flex items-center gap-1.5 min-w-0">
              <span class="inline-flex w-3.5 h-3.5 shrink-0" style="color:#ef4444">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg>
              </span>
              <span class="text-xs font-medium truncate flex-1">7/19/2026, 4:12:45 PM</span>
            </div>
            <div class="flex items-center gap-1.5 mt-0.5 pl-5">
              <span class="text-xs text-muted-foreground" style="font-size:10px">1,203.67ms</span>
              <span class="px-1 py-0 rounded uppercase text-red-400 bg-red-500/20" style="font-size:9px;font-weight:600">failed</span>
              <span class="px-1 py-0 rounded uppercase text-violet-400 bg-violet-500/20" style="font-size:9px;font-weight:600">API</span>
            </div>
          </button>
          <button class="w-full text-left p-2.5 rounded-md border bg-muted/20 hover:bg-muted/40 transition-colors">
            <div class="flex items-center gap-1.5 min-w-0">
              <span class="inline-flex w-3.5 h-3.5 shrink-0" style="color:#10b981">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>
              </span>
              <span class="text-xs font-medium truncate flex-1">7/19/2026, 3:58:02 PM</span>
            </div>
            <div class="flex items-center gap-1.5 mt-0.5 pl-5">
              <span class="text-xs text-muted-foreground" style="font-size:10px">156.89ms</span>
            </div>
          </button>
        </div>
      </div>

      <!-- RIGHT: execution detail -->
      <div class="flex-1 min-w-0 overflow-y-auto">
        <div class="space-y-2">
          <!-- Inputs -->
          <div class="flex items-center justify-between gap-2">
            <div class="text-sm font-semibold">Inputs</div>
            <div class="flex items-center gap-0.5 flex-wrap justify-end">
              <button class="btn-sm btn-ghost" style="height:1.5rem;padding:0 0.5rem;gap:0.25rem">
                <span class="text-xs">Bring to Canvas</span>
              </button>
              <button class="btn-sm btn-ghost" style="height:1.5rem;padding:0 0.5rem;gap:0.25rem">
                <span class="text-xs">Copy</span>
              </button>
            </div>
          </div>
          <pre class="text-xs bg-muted/30 p-3 rounded-md max-h-40 overflow-auto whitespace-pre-wrap break-all">{"message": "Hello world", "context": {"user_id": 42, "source": "chat"}}</pre>

          <!-- Outputs -->
          <div class="flex items-center justify-between gap-2">
            <div class="text-sm font-semibold">Outputs</div>
            <button class="btn-sm btn-ghost" style="height:1.5rem;padding:0 0.5rem;gap:0.25rem">
              <span class="text-xs">Copy</span>
            </button>
          </div>
          <pre class="text-xs bg-muted/30 p-3 rounded-md max-h-40 overflow-auto whitespace-pre-wrap break-all">{"result": "Successfully processed", "tokens": 150}</pre>

          <!-- Node Execution Logs -->
          <div class="space-y-2">
            <div class="flex items-center justify-between gap-2">
              <div class="text-sm font-semibold">Node Execution Logs</div>
              <div class="flex gap-1">
                <button class="text-xs" style="height:1.5rem;padding:0 0.5rem">Expand All</button>
                <button class="text-xs" style="height:1.5rem;padding:0 0.5rem">Collapse All</button>
              </div>
            </div>
            <div class="space-y-1">
              <!-- Node 1 -->
              <div class="border rounded-md overflow-hidden">
                <button class="w-full flex items-center gap-2 p-2 text-left hover:bg-muted/30 transition-colors">
                  <span class="inline-flex w-4 h-4 shrink-0 text-muted-foreground">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>
                  </span>
                  <span class="inline-flex w-4 h-4 shrink-0" style="color:#10b981">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>
                  </span>
                  <span class="text-sm font-medium truncate flex-1">LLM Chat</span>
                  <span class="text-xs text-muted-foreground shrink-0">llm</span>
                  <span class="text-xs text-muted-foreground shrink-0">245.32ms</span>
                </button>
              </div>
              <!-- Node 2 -->
              <div class="border rounded-md overflow-hidden">
                <button class="w-full flex items-center gap-2 p-2 text-left hover:bg-muted/30 transition-colors">
                  <span class="inline-flex w-4 h-4 shrink-0 text-muted-foreground">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m9 18 6-6-6-6"/></svg>
                  </span>
                  <span class="inline-flex w-4 h-4 shrink-0" style="color:#ef4444">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg>
                  </span>
                  <span class="text-sm font-medium truncate flex-1">HTTP Request</span>
                  <span class="px-1.5 py-0.5 rounded text-amber-600 bg-amber-500/10 shrink-0 font-medium" style="font-size:10px">attempt 1/3 failed</span>
                  <span class="text-xs text-muted-foreground shrink-0">http</span>
                  <span class="text-xs text-muted-foreground shrink-0">1,203.67ms</span>
                </button>
                <div class="border-t bg-muted/10 p-3 space-y-2">
                  <div class="space-y-1">
                    <div class="text-xs font-medium text-red-500">Error</div>
                    <pre class="text-xs bg-red-500/10 text-red-400 p-2 rounded-md whitespace-pre-wrap break-all">Connection timeout after 30s - target server unreachable</pre>
                  </div>
                  <div class="space-y-1">
                    <div class="text-xs font-medium text-muted-foreground">Output</div>
                    <pre class="text-xs bg-muted/30 p-2 rounded-md max-h-40 overflow-auto whitespace-pre-wrap break-all">{"error": "timeout", "url": "https://api.example.com/data"}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>`;

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: MOBILE_VIEWPORT,
    deviceScaleFactor: 2,
  });
  const page = await context.newPage();

  await page.setContent(HTML, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await page.screenshot({
    path: resolve(ARTIFACTS, "history-dialog-mobile-portrait.png"),
    fullPage: false,
  });

  console.log("Screenshot saved to", resolve(ARTIFACTS, "history-dialog-mobile-portrait.png"));
  await browser.close();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
