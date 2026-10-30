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
        if (message.method === "Page.javascriptDialogOpening") {
          // 门户常用 alert 提示错误或成功；无人点击会卡住页面，直接确认掉。
          this.send("Page.handleJavaScriptDialog", { accept: true }).catch(() => {});
        }
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

function handleServicePageExpression(keyword) {
  return `(() => {
    const byId = (id) => document.getElementById(id);
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const wanted = ${JSON.stringify(keyword || "移动")};
    const aliases = {
      "移动": ["mobile", "cmcc", "yidong"],
      "电信": ["telecom", "dx", "dianxin"],
      "联通": ["unicom", "lt", "liantong"],
    };
    const extra = aliases[wanted] || [];
    const hit = (value) => {
      const text = String(value || "");
      return text.includes(wanted) || extra.some((alias) => text.toLowerCase().includes(alias));
    };
    const info = () => ({
      selected: byId("net_access_type") ? String(byId("net_access_type").value || "") : "",
      selectedText: clean(byId("selectDisname") && byId("selectDisname").innerHTML),
      serviceCount:
        typeof services !== "undefined" && Array.isArray(services) ? services.length : 0,
      submitted: window.__cqutServiceSubmitted === true,
      query: String(location.search || "").slice(0, 200),
    });
    const submit = () => {
      if (window.__cqutServiceSubmitted) return "already";
      const link = byId("loginLink");
      if (!link) return "no-button";
      window.__cqutServiceSubmitted = true;
      setTimeout(() => link.click(), 200);
      return "clicked";
    };
    const state = info();
    // 服务已经选好（包括上一次尝试选好的），直接点页面上的登录按钮。
    if (state.selected && state.selectedText && state.selectedText !== "请选择服务") {
      return { ok: true, action: "login", submit: submit(), ...state };
    }
    // 服务列表已渲染：点文字匹配上运营商的那一项。
    const items = [
      ...document.querySelectorAll(
        "#serviceContent [onclick], #serviceContent div, #serviceContent span, #serviceContent a, #serviceContent li"
      ),
    ];
    const matches = items
      .map((el) => {
        const text = clean(el.innerText || el.textContent);
        return {
          el,
          text,
          raw: text + " " + (el.getAttribute("onclick") || ""),
        };
      })
      .filter((x) => x.raw && hit(x.raw))
      .sort((a, b) => a.text.length - b.text.length);
    if (matches.length) {
      const item = matches[0];
      item.el.click();
      if (!byId("net_access_type") || !byId("net_access_type").value) {
        const code = item.el.getAttribute("onclick") || "";
        const found = code.match(/selectService\\(\\s*'([^']+)'\\s*,\\s*'([^']*)'/);
        if (found) {
          const field = byId("net_access_type");
          if (field) field.value = found[1];
          const shown = byId("selectDisname");
          if (shown && found[2]) shown.innerHTML = found[2];
        }
      }
      return {
        ok: true,
        action: "select-login",
        picked: item.text,
        submit: submit(),
        ...info(),
      };
    }
    // 列表还在内存里：直接调用页面自己的 selectService 完成选择。
    if (typeof services !== "undefined" && Array.isArray(services)) {
      for (let i = 0; i < services.length; i += 1) {
        const item = services[i] || {};
        const name = String(item.serviceName || "");
        const show = String(item.serviceShowName || "");
        const label = name + " " + show;
        if (hit(label) || /中国移动|移动|校园网|电信|联通/.test(label)) {
          try {
            selectService(name, show || name, i);
          } catch (e) {
            // 页面脚本可能因缺少运营商密码框而中断，下面直接写隐藏字段兜底。
          }
          const field = byId("net_access_type");
          if (field) field.value = name;
          const shown = byId("selectDisname");
          if (shown) shown.innerHTML = show || name;
          return {
            ok: true,
            action: "select-login",
            picked: show || name,
            submit: submit(),
            ...info(),
          };
        }
      }
    }
    // 服务列表还没拉下来：点开服务框，让页面自己去请求服务列表。
    const top = byId("serviceShowHideTop");
    if (top) {
      top.click();
      return { ok: false, action: "open", ...info() };
    }
    return { ok: false, action: "none", ...info() };
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
    let formDeadline = Date.now() + 25000;
    let triedRoot = false;
    let sawUisSuccess = false;
    let reloadedAfterSuccess = false;
    let serviceAttempts = 0;
    let lastServiceAttemptAt = 0;
    let serviceProbe = null;
    let serviceSubmitted = false;
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
      const servicePage =
        /请选择服务|选择服务/.test(text) || /选择服务/.test(lastState.title || "");
      if (
        !submitted &&
        !serviceSubmitted &&
        serviceAttempts < 6 &&
        servicePage &&
        Date.now() - lastServiceAttemptAt > 3000
      ) {
        // 门户有时不直接给登录表单，而是先要求选择运营商服务。
        // 服务项藏在下拉框里，页面加载后由 getServices 动态填充；
        // 这里按设置里的关键字选中服务，再点页面自己的登录按钮。
        lastServiceAttemptAt = Date.now();
        serviceAttempts += 1;
        const picked = await devtools.evaluate(
          handleServicePageExpression(input.serviceKeyword || "移动")
        );
        serviceProbe = picked;
        if (picked?.action === "select-login" || picked?.action === "login") {
          serviceSubmitted = true;
          await sleep(2000);
          continue;
        }
        await sleep(1200);
        continue;
      }
      if (!submitted && Date.now() >= formDeadline) {
        if (!triedRoot) {
          // 深链里的 AC 参数可能已经失效或只能用一次。像用户手动打开门户
          // 那样，从门户根地址重新进入，让 AC 重新下发一套登录参数。
          triedRoot = true;
          try {
            await devtools.send("Page.navigate", {
              url: new URL(input.url).origin + "/",
            });
          } catch {
            // 保留当前页面继续观察。
          }
          await sleep(2000);
          formDeadline = Date.now() + 60000;
          continue;
        }
        process.stdout.write(JSON.stringify({
          ok: false,
          stage: "form-not-found",
          reason: "未进入统一认证登录表单",
          url: lastState?.url || "",
          title: lastState?.title || "",
          readyState: lastState?.ready || "",
          text: (lastState?.text || "").slice(0, 1200),
          serviceAction: serviceProbe?.action || "",
          servicePicked: serviceProbe?.picked || "",
          serviceSelected: serviceProbe?.selectedText || "",
          serviceCount: serviceProbe?.serviceCount ?? null,
          serviceQuery: serviceProbe?.query || "",
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
      title: lastState?.title || "",
      readyState: lastState?.ready || "",
      text: (lastState?.text || "").slice(0, 1200),
      serviceAction: serviceProbe?.action || "",
      servicePicked: serviceProbe?.picked || "",
      serviceSelected: serviceProbe?.selectedText || "",
      serviceCount: serviceProbe?.serviceCount ?? null,
      serviceQuery: serviceProbe?.query || "",
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
