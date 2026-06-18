"use strict";

const PDF_BTN_ID = "esmile009-pdf-download";
const STATUS_ID = "esmile009-pdf-status";

function findDownloadLink() {
  return (
    document.querySelector("a.download-btn[href]") ||
    document.querySelector('a[download][href*=".xlsx" i]') ||
    document.querySelector('a[download][href*=".xls" i]')
  );
}

function injectStyles() {
  if (document.getElementById("esmile009-pdf-styles")) return;

  const style = document.createElement("style");
  style.id = "esmile009-pdf-styles";
  style.textContent = `
    .esmile009-pdf-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      min-height: 48px;
      margin-top: 12px;
      border: 0;
      border-radius: 10px;
      background: #059669;
      color: #fff;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s ease;
    }
    .esmile009-pdf-btn:hover:not(:disabled) {
      background: #047857;
    }
    .esmile009-pdf-btn:disabled {
      opacity: 0.72;
      cursor: wait;
    }
    .esmile009-pdf-status {
      margin-top: 10px;
      font-size: 0.82rem;
      color: #6b7280;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .esmile009-pdf-status.is-error {
      color: #b91c1c;
    }
  `;
  document.head.appendChild(style);
}

function setStatus(text, isError = false) {
  const el = document.getElementById(STATUS_ID);
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("is-error", isError);
}

function injectPdfButton() {
  if (document.getElementById(PDF_BTN_ID)) return;

  const link = findDownloadLink();
  if (!link) return;

  injectStyles();

  const btn = document.createElement("button");
  btn.id = PDF_BTN_ID;
  btn.type = "button";
  btn.className = "esmile009-pdf-btn";
  btn.textContent = "PDF で保存";

  const status = document.createElement("div");
  status.id = STATUS_ID;
  status.className = "esmile009-pdf-status";
  status.setAttribute("aria-live", "polite");

  btn.addEventListener("click", async () => {
    const excelUrl = new URL(link.getAttribute("href") || "", window.location.href).href;
    const excelName =
      link.getAttribute("download") ||
      decodeURIComponent(new URL(excelUrl).pathname.split("/").pop() || "document.xlsx");

    btn.disabled = true;
    setStatus("Excel を取得して PDF に変換しています…");

    try {
      const response = await chrome.runtime.sendMessage({
        action: "convertToPdf",
        excelUrl,
        excelFilename: excelName,
      });

      if (!response?.ok) {
        throw new Error(response?.error || "変換に失敗しました");
      }

      setStatus(`保存しました: ${response.filename || "PDF"}\nAPI: ${response.apiBase || "(不明)"}`);
    } catch (err) {
      setStatus(String(err?.message || err), true);
    } finally {
      btn.disabled = false;
    }
  });

  link.insertAdjacentElement("afterend", btn);
  btn.insertAdjacentElement("afterend", status);
}

function boot() {
  injectPdfButton();

  const observer = new MutationObserver(() => {
    injectPdfButton();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
