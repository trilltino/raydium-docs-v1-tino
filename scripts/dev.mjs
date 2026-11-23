#!/usr/bin/env node
// Preview the docs locally with `mint dev`, with working Copy page and View as Markdown buttons.
//
// Those buttons fetch `<page>.md`. `mint dev` serves a page's Markdown only at `/_markdown/<page>`
// and answers `<page>.md` with a 404, so Copy page copies nothing. This script runs `mint dev` on a
// free internal port and puts a small proxy in front of it on the port you ask for. The proxy maps
// `<page>.md` to `/_markdown/<page>` and passes everything else through unchanged, including the
// WebSocket that drives hot reload. The review site on the VPS does the same mapping in nginx (see
// deploy-vps.py).
//
// Run from the repo root, in place of `mint dev`:
//   node scripts/dev.mjs                 # http://localhost:3000
//   node scripts/dev.mjs --port 4317     # other `mint dev` flags are passed through
//
// Needs the Mintlify CLI on PATH (`npm i -g mint`). Stop it with Ctrl+C.

import { spawn, spawnSync } from "node:child_process";
import http from "node:http";
import net from "node:net";

const MARKDOWN_PAGE = /^\/(?!_)(.+)\.md$/;
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function parseArgs(argv) {
  let port = 3000;
  let open = true;
  const rest = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--port") port = Number(argv[++i]);
    else if (arg.startsWith("--port=")) port = Number(arg.slice("--port=".length));
    else if (arg === "--no-open") open = false;
    else rest.push(arg);
  }
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    console.error("--port needs a number between 1 and 65535");
    process.exit(2);
  }
  return { port, open, rest };
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

// `/docs/en/foo.md?x=1` becomes `/_markdown/docs/en/foo?x=1`. Paths under `/_` are left alone.
function rewrite(url) {
  const q = url.indexOf("?");
  const path = q === -1 ? url : url.slice(0, q);
  const match = MARKDOWN_PAGE.exec(path);
  return match ? `/_markdown/${match[1]}${q === -1 ? "" : url.slice(q)}` : url;
}

function endToEnd(rawHeaders) {
  const kept = [];
  for (let i = 0; i < rawHeaders.length; i += 2) {
    if (!HOP_BY_HOP.has(rawHeaders[i].toLowerCase())) kept.push(rawHeaders[i], rawHeaders[i + 1]);
  }
  return kept;
}

function proxyRequest(innerPort, agent) {
  return (req, res) => {
    const path = req.method === "GET" || req.method === "HEAD" ? rewrite(req.url) : req.url;
    const upstream = http.request(
      { host: "127.0.0.1", port: innerPort, method: req.method, path, headers: endToEnd(req.rawHeaders), agent },
      (up) => {
        res.writeHead(up.statusCode, up.statusMessage, endToEnd(up.rawHeaders));
        up.pipe(res);
      },
    );
    upstream.on("error", () => {
      if (res.headersSent) return res.destroy();
      res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
      res.end("mint dev is not answering yet. Wait for it to finish starting, then reload.\n");
    });
    res.on("close", () => {
      if (!res.writableFinished) upstream.destroy();
    });
    req.pipe(upstream);
  };
}

function proxyUpgrade(innerPort) {
  return (req, socket, head) => {
    const upstream = net.connect(innerPort, "127.0.0.1", () => {
      const lines = [`${req.method} ${req.url} HTTP/${req.httpVersion}`];
      for (let i = 0; i < req.rawHeaders.length; i += 2) lines.push(`${req.rawHeaders[i]}: ${req.rawHeaders[i + 1]}`);
      upstream.write(`${lines.join("\r\n")}\r\n\r\n`);
      if (head.length) upstream.write(head);
      upstream.pipe(socket);
      socket.pipe(upstream);
    });
    upstream.on("error", () => socket.destroy());
    socket.on("error", () => upstream.destroy());
  };
}

function answers(innerPort) {
  return new Promise((resolve) => {
    const req = http.get({ host: "127.0.0.1", port: innerPort, path: "/", agent: false }, (res) => {
      res.resume();
      resolve(res.statusCode < 500);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(5000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

function openBrowser(url) {
  const [cmd, args] =
    process.platform === "win32"
      ? ["cmd", ["/c", "start", "", url]]
      : [process.platform === "darwin" ? "open" : "xdg-open", [url]];
  spawn(cmd, args, { detached: true, stdio: "ignore" }).on("error", () => {}).unref();
}

const { port, open, rest } = parseArgs(process.argv.slice(2));
const innerPort = await freePort();
const url = `http://localhost:${port}`;
let child;
let stopping = false;

function stop(code) {
  if (stopping) return;
  stopping = true;
  if (child && child.exitCode === null && child.signalCode === null) {
    if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    else {
      try {
        process.kill(-child.pid, "SIGTERM");
      } catch {}
    }
  }
  process.exit(code);
}

const proxy = http.createServer(proxyRequest(innerPort, new http.Agent({ keepAlive: true })));
proxy.on("upgrade", proxyUpgrade(innerPort));
proxy.on("error", (err) => {
  console.error(err.code === "EADDRINUSE" ? `Port ${port} is already in use. Stop what is on it, or pass --port <n>.` : err.message);
  stop(1);
});
await new Promise((resolve) => proxy.listen(port, resolve));

console.log(`Starting mint dev on internal port ${innerPort}. Open ${url}, not the port mint dev prints.`);
child = spawn("mint", ["dev", "--port", String(innerPort), "--no-open", ...rest], {
  stdio: "inherit",
  shell: process.platform === "win32",
  detached: process.platform !== "win32",
});
child.on("error", (err) => {
  console.error(`Could not start mint dev: ${err.message}. Install it with \`npm i -g mint\`.`);
  stop(1);
});
child.on("exit", (code) => {
  if (!stopping) console.error(`mint dev exited${code === null ? "" : ` with code ${code}`}.`);
  stop(code ?? 1);
});
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));

while (!stopping && !(await answers(innerPort))) await new Promise((resolve) => setTimeout(resolve, 1000));
if (!stopping) {
  console.log(`\nDocs preview with Copy page support: ${url}\n`);
  if (open) openBrowser(url);
}
