"use strict";

const { DEFAULT_API_BASE, resolveApiBase, shouldMigrateApiBase } =
  globalThis.Esmile009ApiConfig;

async function save() {
  const input = /** @type {HTMLInputElement} */ (document.getElementById("apiBaseUrl"));
  const status = document.getElementById("status");
  const apiBaseUrl = globalThis.Esmile009ApiConfig.normalizeBase(input.value);

  status.textContent = "";

  try {
    if (!/^https?:\/\//i.test(apiBaseUrl)) {
      status.textContent = "http/https で始まる URL を入力してください";
      return;
    }

    await chrome.storage.sync.set({ apiBaseUrl });

    status.textContent = "保存しました";
  } catch (e) {
    status.textContent = `保存に失敗しました: ${String(e)}`;
  }
}

async function restore() {
  const input = /** @type {HTMLInputElement} */ (document.getElementById("apiBaseUrl"));
  const { apiBaseUrl } = await chrome.storage.sync.get(["apiBaseUrl"]);
  if (shouldMigrateApiBase(apiBaseUrl)) {
    await chrome.storage.sync.set({ apiBaseUrl: DEFAULT_API_BASE });
    input.value = DEFAULT_API_BASE;
    return;
  }
  input.value = resolveApiBase(apiBaseUrl);
}

document.addEventListener("DOMContentLoaded", () => {
  restore();
  document.getElementById("save")?.addEventListener("click", save);
});
