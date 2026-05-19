"use strict";

const DEFAULT_API_BASE = "https://engawa2525.com/esmile009";

chrome.runtime.onInstalled.addListener(async () => {
  const { apiBaseUrl } = await chrome.storage.sync.get(["apiBaseUrl"]);
  if (typeof apiBaseUrl !== "string" || !apiBaseUrl.trim()) {
    await chrome.storage.sync.set({ apiBaseUrl: DEFAULT_API_BASE });
  }
});
