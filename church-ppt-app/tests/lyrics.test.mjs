// node --test church-ppt-app/tests
import test from "node:test";
import assert from "node:assert/strict";
import * as L from "../js/lyrics.js";

const SONG = `제목: 테스트 곡
아티스트: 누군가
순서: V1 C V2 C B C

[Verse 1]
하나
둘
셋

[Chorus]
후렴 하나
후렴 둘

[Verse 2]
이절 하나

이절 둘

[Bridge]
브릿지
`;

test("labels", () => {
  assert.equal(L.normalizeLabel("[1절]"), "Verse 1");
  assert.equal(L.normalizeLabel("V2"), "Verse 2");
  assert.equal(L.normalizeLabel("후렴"), "Chorus");
  assert.equal(L.normalizeLabel("(후렴)"), "Chorus");
  assert.equal(L.labelAbbrev("Verse 1"), "V1");
  assert.ok(L.isHeaderLine("Chorus:"));
  assert.ok(!L.isHeaderLine("C"));
});

test("order", () => {
  assert.deepEqual(L.parseOrder("V1 C V2 C B C"), ["Verse 1", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus"]);
  assert.deepEqual(L.parseOrder("Verse 1 Chorus"), ["Verse 1", "Chorus"]);
  assert.deepEqual(L.parseOrder("1절 → 후렴"), ["Verse 1", "Chorus"]);
});

test("parse / roundtrip (Windows 프로그램이 저장한 형식)", () => {
  const s = L.parseSongText("﻿" + SONG.replace(/\n/g, "\r\n"));
  assert.equal(s.title, "테스트 곡");
  assert.deepEqual(s.sections.map((x) => x.label), ["Verse 1", "Chorus", "Verse 2", "Bridge"]);
  assert.deepEqual(s.sections[2].lines, ["이절 하나", "", "이절 둘"]);
  assert.deepEqual(s.sections[3].lines, ["브릿지"]);
  assert.deepEqual(L.parseSongText(L.songToText(s)), s);
  const { seq } = L.resolveOrder(s);
  assert.deepEqual(seq.map((x) => x.label), ["Verse 1", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus"]);
});

test("auto structure: 반복 연 = Chorus, 반복 없으면 그대로", () => {
  let r = L.autoStructure("일절\n둘\n\n할렐루야\n아멘\n\n이절\n\n할렐루야\n아멘");
  assert.deepEqual(r.sections.map((x) => x.label), ["Verse 1", "Chorus", "Verse 2"]);
  assert.deepEqual(r.order, ["Verse 1", "Chorus", "Verse 2", "Chorus"]);
  r = L.autoStructure("가\n나\n\n다");
  assert.equal(r.sections.length, 1);
  assert.equal(r.sections[0].label, "");
});

test("auto structure: 찬송가 1. 2. 와 (후렴)", () => {
  const r = L.autoStructure("1. 첫째 절\n줄\n\n(후렴)\n후렴 가사\n\n2. 둘째 절\n줄");
  assert.deepEqual(r.sections.map((x) => x.label), ["Verse 1", "Chorus", "Verse 2"]);
  assert.deepEqual(r.order, ["Verse 1", "Chorus", "Verse 2", "Chorus"]);
});

test("songFromTxt: 구분 없는 옛 메모장 파일도 자동으로 나눔", () => {
  const s = L.songFromTxt("일절\n둘\n\n할렐루야\n아멘\n\n이절\n\n할렐루야\n아멘", "파일이름");
  assert.equal(s.title, "파일이름");
  assert.deepEqual(s.sections.map((x) => x.label), ["Verse 1", "Chorus", "Verse 2"]);
  const t = L.songFromTxt(SONG);
  assert.deepEqual(t.order, ["Verse 1", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus"]);
});

test("clean pasted", () => {
  assert.equal(L.cleanPastedLyrics("G  D/F#  Em7\n주님의 사랑 (x2)\n\n\n출처: https://x.com\n찬양해 반복"), "주님의 사랑\n\n찬양해");
});

test("chunk", () => {
  assert.deepEqual(L.chunkLines(["a", "b", "c", "d", "e"], 2), [["a", "b"], ["c", "d"], ["e"]]);
  assert.deepEqual(L.chunkLines(["a", "", "b", "c"], 4), [["a"], ["b", "c"]]);
});
