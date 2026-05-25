"use strict";

const DEFAULT_API_BASE = "https://engawa2525.com/esmile009";

function normalizeBase(raw) {
  return String(raw || "")
    .trim()
    .replace(/\/+$/, "");
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

async function getApiBaseUrl() {
  const { apiBaseUrl } = await chrome.storage.sync.get(["apiBaseUrl"]);
  return normalizeBase(apiBaseUrl) || DEFAULT_API_BASE;
}

function waitForDownloadComplete(downloadId) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      chrome.downloads.onChanged.removeListener(onChanged);
      reject(new Error("PDF の保存がタイムアウトしました"));
    }, 120_000);

    function onChanged(delta) {
      if (delta.id !== downloadId || !delta.state) return;

      if (delta.state.current === "complete") {
        clearTimeout(timeout);
        chrome.downloads.onChanged.removeListener(onChanged);
        resolve();
      } else if (delta.state.current === "interrupted") {
        clearTimeout(timeout);
        chrome.downloads.onChanged.removeListener(onChanged);
        reject(new Error("PDF の保存が中断されました"));
      }
    }

    chrome.downloads.onChanged.addListener(onChanged);
  });
}

async function convertAndDownload(excelUrl, excelFilename, pdfFilename) {
  const excelRes = await fetch(excelUrl, { method: "GET", cache: "no-store" });
  if (!excelRes.ok) {
    throw new Error(`Excel の取得に失敗しました (${excelRes.status})`);
  }

  const excelBlob = await excelRes.blob();
  if (!excelBlob.size) {
    throw new Error("Excel ファイルが空です");
  }

  const form = new FormData();
  form.append("file", excelBlob, excelFilename);

  const apiBase = await getApiBaseUrl();
  const convertRes = await fetch(`${apiBase}/convert`, {
    method: "POST",
    body: form,
    cache: "no-store",
  });

  if (!convertRes.ok) {
    const detail = await convertRes.text();
    throw new Error(`PDF 変換 API エラー (${convertRes.status}): ${detail}`);
  }

  const pdfBuffer = await convertRes.arrayBuffer();
  if (!pdfBuffer.byteLength) {
    throw new Error("PDF の生成結果が空です");
  }

  const pdfBase64 = arrayBufferToBase64(pdfBuffer);
  const downloadId = await chrome.downloads.download({
    url: `data:application/pdf;base64,${pdfBase64}`,
    filename: pdfFilename,
    saveAs: false,
  });

  await waitForDownloadComplete(downloadId);
  return { filename: pdfFilename, apiBase };
}

chrome.runtime.onInstalled.addListener(async () => {
  const { apiBaseUrl } = await chrome.storage.sync.get(["apiBaseUrl"]);
  if (typeof apiBaseUrl !== "string" || !apiBaseUrl.trim()) {
    await chrome.storage.sync.set({ apiBaseUrl: DEFAULT_API_BASE });
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.action !== "convertToPdf") return;

  convertAndDownload(message.excelUrl, message.excelFilename, message.pdfFilename)
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));

  return true;
});
