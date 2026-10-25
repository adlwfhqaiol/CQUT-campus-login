import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";

const EDGE_CANDIDATES = [
  process.env.ProgramFiles &&
    path.join(process.env.ProgramFiles, "Microsoft", "Edge", "Application", "msedge.exe"),
  process.env["ProgramFiles(x86)"] &&
    path.join(
      process.env["ProgramFiles(x86)"],
      "Microsoft",
      "Edge",
      "Application",
      "msedge.exe"
    ),
  process.env.LOCALAPPDATA &&
    path.join(
      process.env.LOCALAPPDATA,
      "Microsoft",
      "Edge",
      "Application",
      "msedge.exe"
    ),
].filter(Boolean);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

class DevTools {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl);
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
    });
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(String(event.data));
      if (!message.id) {
        if (message.method) this.events.push(message);
        return;
      }
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || "页面脚本执行失败");
    }
    return result.result?.value;
  }

  close() {
    if (this.ws) this.ws.close();
  }
}

async function findPage(port) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const tabs = await response.json();
      const page = tabs.find((tab) => tab.type === "page" && tab.webSocketDebuggerUrl);
      if (page) return page;
    } catch {
      // Edge is still starting.
    }
    await sleep(250);
  }
  throw new Error("Edge 调试端口启动超时");
}

async function networkOnline() {
  try {
    const response = await fetch("http://connect.rom.miui.com/generate_204", {
      redirect: "manual",
      signal: AbortSignal.timeout(4000),
      cache: "no-store",
    });
    return response.status === 204;
  } catch {
    return false;
  }
}

function isTrustedSchoolHost(host) {
  const normalizedHost = String(host || "").toLowerCase();
  return (
    normalizedHost === "202.202.145.132" ||
    normalizedHost === "cqut.edu.cn" ||
    normalizedHost.endsWith(".cqut.edu.cn")
  );
}

function pageStateExpression() {
  return `(() => {
    const visible = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
    };
    const inputs = [...document.querySelectorAll("input")];
    return {
      url: location.href,
      ready: document.readyState,
      title: document.title || "",
      text: (document.body?.innerText || "").slice(0, 2500),
      hasVisibleText: inputs.some((x) => visible(x) && ["text", "tel", "email"].includes(x.type || "text")),
      hasVisiblePassword: inputs.some((x) => visible(x) && x.type === "password"),
    };
  })()`;
}

function fillLoginExpression(username, password) {
  return `(() => {
    const visible = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
    };
    const setValue = (el, value) => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    };
    const user = [...document.querySelectorAll("input")].find(
      (x) => visible(x) && ["text", "tel", "email", ""].includes(x.type) &&
        /学号|账号|工号|用户名/.test((x.placeholder || "") + (x.name || ""))
    ) || [...document.querySelectorAll("input")].find(
      (x) => visible(x) && ["text", "tel", "email", ""].includes(x.type)
    );
    const pass = [...document.querySelectorAll("input")].find(
      (x) => visible(x) && x.type === "password"
    );
    if (!user || !pass) return { ok: false, reason: "找不到账号或密码输入框" };
    setValue(user, ${JSON.stringify(username)});
    setValue(pass, ${JSON.stringify(password)});
    user.dispatchEvent(new Event("blur", { bubbles: true }));
    pass.dispatchEvent(new Event("blur", { bubbles: true }));
    const controls = [
      ...document.querySelectorAll(
        'button, input[type="submit"], input[type="button"], [role="button"]'
      ),
    ];
    const button = controls.find(
      (x) =>
        visible(x) &&
        /登录/.test(((x.innerText || "") + " " + (x.value || "")).trim())
    );
    if (button) {
      button.disabled = false;
      button.click();
      return { ok: true, reason: "已提交登录" };
    }
    const form = pass.form;
    if (form) {
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else HTMLFormElement.prototype.submit.call(form);
      return { ok: true, reason: "已通过表单提交登录" };
    }
    return {
      ok: false,
      reason: "找不到登录按钮或登录表单（页面按钮数：" + controls.length + "）",
    };
  })()`;
}

async function main() {
  if (typeof WebSocket !== "function") {
    throw new Error("当前 Node.js 不支持内置 WebSocket，请升级到 Node.js 22 或更高版本");
  }
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  if (!input.url || !input.username || !input.password) {
    throw new Error("浏览器登录参数不完整");
  }
  const edge = EDGE_CANDIDATES.find((candidate) => fs.existsSync(candidate));
  if (!edge) throw new Error("找不到 Microsoft Edge");

  const port = await freePort();
  const profile = path.join(
    process.env.LOCALAPPDATA || os.homedir(),
    "CQUTCampusLogin",
    "edge-profile"
  );
  fs.mkdirSync(profile, { recursive: true });
  const browser = spawn(edge, [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
    "--disable-background-networking",
    "--disable-blink-features=AutomationControlled",
    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36 Edg/155.0.0.0",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    "about:blank",
  ], { stdio: "ignore", windowsHide: true });

  let devtools;
  try {
    const target = await findPage(port);
    devtools = new DevTools(target.webSocketDebuggerUrl);
    await devtools.connect();
    await devtools.send("Page.enable");
    await devtools.send("Runtime.enable");
    await devtools.send("Network.enable");
    await devtools.send("Page.navigate", { url: input.url });

    let submitted = false;
    let lastState = null;
    const deadline = Date.now() + 120000;
    const formDeadline = Date.now() + 20000;
    let sawUisSuccess = false;
    let reloadedAfterSuccess = false;
    while (Date.now() < deadline) {
      await sleep(500);
      try {
        lastState = await devtools.evaluate(pageStateExpression());
      } catch {
        // A navigation can briefly invalidate the old execution context.
        continue;
      }
      const text = lastState.text || "";
      let pageHost = "";
      try {
        pageHost = new URL(lastState.url || "").hostname;
      } catch {
        // Keep the empty host for an about:blank or transient page.
      }
      if (pageHost === "uis.cqut.edu.cn" && /登录成功/.test(text)) {
        sawUisSuccess = true;
      }
      if (
        sawUisSuccess &&
        !reloadedAfterSuccess &&
        pageHost === "uis.cqut.edu.cn"
      ) {
        reloadedAfterSuccess = true;
        await sleep(1500);
        try {
          await devtools.evaluate("location.reload()");
        } catch {
          // The page may already be navigating.
        }
      }
      if (
        (pageHost === "202.202.145.132" && /成功连接校园网|认证成功/.test(text)) ||
        /\/eportal\/success\.jsp/i.test(lastState.url || "") ||
        (await networkOnline())
      ) {
        process.stdout.write(JSON.stringify({ ok: true, stage: "success", url: lastState.url }) + "\n");
        return;
      }
      if (
        /请输入正确的账号密码|密码错误|验证码错误|用户信息不存在/.test(text)
      ) {
        throw new Error(text.match(/请输入正确的账号密码|密码错误|验证码错误|用户信息不存在/)?.[0] || "认证失败");
      }
      if (!submitted && lastState.hasVisibleText && lastState.hasVisiblePassword) {
        if (!isTrustedSchoolHost(pageHost)) {
          throw new Error(`登录页跳转到了未授权主机，已停止填写凭据：${pageHost || "unknown"}`);
        }
        const result = await devtools.evaluate(
          fillLoginExpression(input.username, input.password)
        );
        if (!result?.ok) throw new Error(result?.reason || "填写登录表单失败");
        submitted = true;
      }
      if (!submitted && Date.now() >= formDeadline) {
        process.stdout.write(JSON.stringify({
          ok: false,
          stage: "form-not-found",
          reason: "未进入统一认证登录表单",
          url: lastState?.url || "",
          requests: devtools.events
            .filter((event) => event.method === "Network.requestWillBeSent")
            .filter((event) => event.params?.type === "Document")
            .slice(-20)
            .map((event) => {
              try {
                const url = new URL(event.params.request.url);
                return `${event.params.request.method} ${url.hostname}${url.pathname}`;
              } catch {
                return "invalid-url";
              }
            }),
        }) + "\n");
        return;
      }
      if (submitted && /sid\.cqut\.edu\.cn\/adapter/i.test(lastState.url || "")) {
        await sleep(1500);
      }
    }
    process.stdout.write(JSON.stringify({
      ok: submitted,
      stage: submitted ? "submitted" : "form-not-found",
      url: lastState?.url || "",
      requests: devtools.events
        .filter((event) => event.method === "Network.requestWillBeSent")
        .filter((event) => event.params?.type === "Document")
        .slice(-20)
        .map((event) => {
          try {
            const url = new URL(event.params.request.url);
            return `${event.params.request.method} ${url.hostname}${url.pathname}`;
          } catch {
            return "invalid-url";
          }
        }),
    }) + "\n");
  } finally {
    try {
      if (devtools) {
        await devtools.send("Browser.close");
        devtools.close();
      }
    } catch {
      // The browser may already be closing.
    }
    if (!browser.killed) browser.kill();
  }
}

main().catch((error) => {
  process.stdout.write(JSON.stringify({ ok: false, error: error.message || String(error) }) + "\n");
  process.exitCode = 1;
});
