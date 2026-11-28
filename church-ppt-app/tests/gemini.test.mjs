// 무료 AI(Gemini) 연결 - 실제 서버 대신 가짜 응답으로 시험
import test from "node:test";
import assert from "node:assert/strict";

const store = {};
globalThis.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } };
const G = await import("../js/gemini.js");

function fakeFetch(replies, calls = []) {
  return async (url, opts) => {
    calls.push({ url, opts });
    const r = replies.shift();
    return { ok: r.status === 200, status: r.status, json: async () => r.body };
  };
}
const MODELS = { status: 200, body: { models: [
  { name: "models/gemini-2.0-flash", supportedGenerationMethods: ["generateContent"] },
  { name: "models/gemini-2.5-flash-lite", supportedGenerationMethods: ["generateContent"] },
  { name: "models/gemini-2.5-flash", supportedGenerationMethods: ["generateContent"] },
  { name: "models/gemini-2.5-flash-image", supportedGenerationMethods: ["generateContent"] },
  { name: "models/text-embedding-004", supportedGenerationMethods: ["embedContent"] },
] } };
const answer = (text, finishReason = "STOP") => ({ status: 200, body: { candidates: [{ finishReason, content: { parts: [{ text }] } }] } });

test("키 오류 / 사용량 / 저작권 차단", async () => {
  delete store["cppt.geminiModel"];
  await assert.rejects(G.fetchScripture("요 3:16", "개역개정", { key: "bad", fetchFn: fakeFetch([{ status: 400, body: { error: { message: "API key not valid." } } }]) }), (e) => e.kind === "key");
  store["cppt.geminiModel"] = "gemini-2.5-flash";
  await assert.rejects(G.fetchScripture("요 3:16", "개역개정", { key: "k", fetchFn: fakeFetch([{ status: 429, body: { error: { message: "quota" } } }]) }), (e) => e.kind === "limit");
  delete store["cppt.geminiModel"];
  const calls = [];
  await G.pickModel("k", fakeFetch([MODELS], calls));
  assert.equal(localStorage.getItem("cppt.geminiModel"), "gemini-2.5-flash");
});

test("성경 본문 찾기 + 각주 지우기 + 표시", async () => {
  store["cppt.geminiModel"] = "gemini-2.5-flash";
  const f = fakeFetch([answer("<scripture>\n책: 사도행전\n6:1 그 때에 제자가 더 많아졌는데 1)구제에 빠지므로\n6:2 열두 사도가\n6:3 형제들아\n6:4 우리는\n</scripture>")]);
  const r = await G.fetchScripture("행 6:1-4", "개역개정", { key: "k", fetchFn: f });
  assert.equal(r.book, "사도행전");
  assert.equal(r.verses.length, 4);
  assert.equal(r.verses[0].text, "그 때에 제자가 더 많아졌는데 구제에 빠지므로");
  assert.equal(G.scriptureLabel(r.book, r.verses), "사도행전 6장 1-4절");
  assert.equal(G.scriptureLabel("로마서", [{ c: 8, v: 38 }, { c: 9, v: 1 }]), "로마서 8장 38절 - 9장 1절");
});
