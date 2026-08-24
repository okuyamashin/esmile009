"use strict";

const { resolveApiBase } = globalThis.Esmile009ApiConfig;

async function getApiBaseUrl() {
  const { apiBaseUrl } = await chrome.storage.sync.get(["apiBaseUrl"]);
  return resolveApiBase(apiBaseUrl);
}

async function pingHealth() {
  const el = document.getElementById("out");
  if (!el) return;
  el.textContent = "…読み込み中";

  try {
    const base = await getApiBaseUrl();
    const url = `${base}/health`;
    const res = await fetch(url, { method: "GET", cache: "no-store" });

    const text = await res.text();
    el.textContent = `${res.status} ${res.statusText}\n${text}`;
    if (!res.ok) el.textContent += `\n\nURL=${url}`;
  } catch (e) {
    el.textContent = `例外: ${String(e)}\n\n設定の API URL を確認してください（本番: https://esmile009.engawa5656.com）`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("health")?.addEventListener("click", pingHealth);

  document.getElementById("openOptions")?.addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });
});
