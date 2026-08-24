"use strict";

/** 本番 API（サブドメイン直結・パスプレフィックス不要） */
const DEFAULT_API_BASE = "https://esmile009.engawa5656.com";

/** 以前の Apache 経由 URL（設定に残っていると 404 になる） */
const LEGACY_API_BASES = [
  "https://engawa2525.com/esmile009",
  "http://engawa2525.com/esmile009",
];

function normalizeBase(raw) {
  return String(raw || "")
    .trim()
    .replace(/\/+$/, "");
}

function resolveApiBase(raw) {
  const normalized = normalizeBase(raw);
  if (!normalized) return DEFAULT_API_BASE;
  if (LEGACY_API_BASES.includes(normalized)) return DEFAULT_API_BASE;
  return normalized;
}

function shouldMigrateApiBase(raw) {
  const normalized = normalizeBase(raw);
  return !normalized || LEGACY_API_BASES.includes(normalized);
}

const apiConfig = {
  DEFAULT_API_BASE,
  LEGACY_API_BASES,
  normalizeBase,
  resolveApiBase,
  shouldMigrateApiBase,
};

if (typeof globalThis !== "undefined") {
  globalThis.Esmile009ApiConfig = apiConfig;
}
