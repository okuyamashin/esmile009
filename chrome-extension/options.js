"use strict";

function normalizeBase(raw) {
  return String(raw || "")
    .trim()
    .replace(/\/+$/, "");
}

async function save() {
  const input = /** @type {HTMLInputElement} */ (document.getElementById("apiBaseUrl"));
  const status = document.getElementById("status");
  const apiBaseUrl = normalizeBase(input.value);

  status.textContent = "";

  try {
    // URL っぽさだけ軽く検証（厳密な検証には new URL が必要）
    if (!/^https?:\/\//i.test(apiBaseUrl)) {
      status.textContent = "http/https で始まる URL を入力してください";
      return;
    }
    // host_permissions に無いホストだけは fetch は失敗しうるので README を参照させる

    await chrome.storage.sync.set({ apiBaseUrl });

    status.textContent = "保存しました";
  } catch (e) {
    status.textContent = `保存に失敗しました: ${String(e)}`;
  }
}

async function restore() {
  const input = /** @type {HTMLInputElement} */ (document.getElementById("apiBaseUrl"));
  const { apiBaseUrl } = await chrome.storage.sync.get(["apiBaseUrl"]);
  input.value =
    normalizeBase(apiBaseUrl) || "https://engawa2525.com/esmile009";
}

document.addEventListener("DOMContentLoaded", () => {
  restore();
  document.getElementById("save")?.addEventListener("click", save);
});
