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

test("모델 고르기 + 가사 찾기 + 파트", async () => {
  delete store["cppt.geminiModel"];
  const calls = [];
  const f = fakeFetch([MODELS, answer("찾았습니다.\n<song>\n제목: 테스트 찬양\n아티스트: 마커스\n순서: Verse 1, Chorus, Verse 1, Chorus\n\n[Verse 1]\n첫 줄\n둘째 줄\n\n[Chorus]\n후렴 첫 줄\n</song>")], calls);
  const song = await G.findLyrics("테스트 찬양", "마커스", { key: "k", fetchFn: f });
  assert.equal(song.artist, "마커스");
  assert.deepEqual(song.sections.map((s) => s.label), ["Verse 1", "Chorus"]);
  assert.deepEqual(song.order, ["Verse 1", "Chorus", "Verse 1", "Chorus"]);
  assert.match(calls[1].url, /models\/gemini-2\.5-flash:generateContent$/);
  const body = JSON.parse(calls[1].opts.body);
  assert.deepEqual(body.tools, [{ google_search: {} }]);
  assert.equal(calls[1].opts.headers["x-goog-api-key"], "k");
});

test("구분 없는 가사는 자동 나누기", async () => {
  const f = fakeFetch([answer("<song>\n제목: 곡\n\n일절 가사\n둘째\n\n할렐루야\n아멘\n\n이절 가사\n\n할렐루야\n아멘\n</song>")]);
  const song = await G.findLyrics("곡", "", { key: "k", fetchFn: f });
  assert.deepEqual(song.sections.map((s) => s.label), ["Verse 1", "Chorus", "Verse 2"]);
});

test("저작권 차단 / 못 찾음 / 키 오류 / 사용량", async () => {
  await assert.rejects(G.findLyrics("곡", "", { key: "k", fetchFn: fakeFetch([answer("", "RECITATION")]) }), (e) => e.kind === "blocked");
  await assert.rejects(G.findLyrics("곡", "", { key: "k", fetchFn: fakeFetch([answer("<not_found>정확한 가사가 없음</not_found>")]) }), (e) => e.kind === "notfound" && /정확한/.test(e.message));
  delete store["cppt.geminiModel"];
  await assert.rejects(G.findLyrics("곡", "", { key: "bad", fetchFn: fakeFetch([{ status: 400, body: { error: { message: "API key not valid." } } }]) }), (e) => e.kind === "key");
  store["cppt.geminiModel"] = "gemini-2.5-flash";
  await assert.rejects(G.findLyrics("곡", "", { key: "k", fetchFn: fakeFetch([{ status: 429, body: { error: { message: "quota" } } }]) }), (e) => e.kind === "limit");
});
