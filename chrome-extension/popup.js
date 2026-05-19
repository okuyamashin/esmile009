"use strict";

function normalizeBase(raw) {
  return String(raw || "")
    .trim()
    .replace(/\/+$/, "");
}

async function getApiBaseUrl() {
  const { apiBaseUrl } = await chrome.storage.sync.get(["apiBaseUrl"]);
  return normalizeBase(apiBaseUrl) || "https://engawa2525.com/esmile009";
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
    if (!res.ok) el.textContent += `\n\nエラー詳細がある場合:\nURL=${url}`;
  } catch (e) {
    el.textContent = `例外: ${String(e)}\n\nよくある原因:\n- manifest の host_permissions に API のオリジンが無い（拡張を再読み込み）\n- API の URL が違う / サーバーが落ちている / 証明書例外など`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("health")?.addEventListener("click", pingHealth);

  document.getElementById("openOptions")?.addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });
});
