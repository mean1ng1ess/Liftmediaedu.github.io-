import test from "node:test";
import assert from "node:assert/strict";
import { parseRef, bskUrl, versesFromCopied } from "../js/bible.js";

test("구절 읽기", () => {
  assert.deepEqual(parseRef("행 6:1-7"), { book: "사도행전", code: "act", c1: 6, v1: 1, c2: 6, v2: 7 });
  assert.deepEqual(parseRef("사도행전 6장 1-7절"), { book: "사도행전", code: "act", c1: 6, v1: 1, c2: 6, v2: 7 });
  assert.deepEqual(parseRef("요 3:16"), { book: "요한복음", code: "jhn", c1: 3, v1: 16, c2: 3, v2: 16 });
  assert.deepEqual(parseRef("시 23편"), { book: "시편", code: "psa", c1: 23, v1: null, c2: 23, v2: null });
  assert.deepEqual(parseRef("롬 8:38-9:2"), { book: "로마서", code: "rom", c1: 8, v1: 38, c2: 9, v2: 2 });
  assert.deepEqual(parseRef("고전 13장 4~7절"), { book: "고린도전서", code: "1co", c1: 13, v1: 4, c2: 13, v2: 7 });
  assert.equal(parseRef("아무말"), null);
  assert.equal(bskUrl(parseRef("행 6:1-7")), "https://www.bskorea.or.kr/bible/korbibReadpage.php?version=GAE&book=act&chap=6");
});

test("복사한 장 본문에서 필요한 절만", () => {
  const copied = `사도행전 6장
일곱 집사를 택하다
1 그 때에 제자가 더 많아졌는데 헬라파 유대인들이 1)구제에 빠지므로
2 열두 사도가 모든 제자를 불러
3 형제들아 너희 가운데서
4 우리는 오로지 기도하는 일과
1) 또는 섬김`;
  const r = versesFromCopied(copied, parseRef("행 6:2-3"));
  assert.deepEqual(r.map((x) => [x.c, x.v]), [[6, 2], [6, 3]]);
  const all = versesFromCopied(copied, parseRef("행 6:1-4"));
  assert.equal(all.length, 4);
  assert.equal(all[0].text, "그 때에 제자가 더 많아졌는데 헬라파 유대인들이 구제에 빠지므로");
});

test("한 줄에 붙은 절 나누기 + 표시", async () => {
  const { refLabel } = await import("../js/bible.js");
  const r = versesFromCopied("1 그 때에 제자가 2)많아졌는데 2 열두 사도가 불러 3 형제들아 너희 가운데서 7 세븐", parseRef("행 6:1-3"));
  assert.deepEqual(r.map((x) => x.v), [1, 2, 3]);
  assert.equal(r[1].text, "열두 사도가 불러");
  assert.equal(r[2].text, "형제들아 너희 가운데서 7 세븐");
  assert.equal(refLabel("사도행전", r), "사도행전 6장 1-3절");
  assert.equal(refLabel("로마서", [{ c: 8, v: 38 }, { c: 9, v: 1 }]), "로마서 8장 38절 - 9장 1절");
});

test("줄마다 절이면 본문 속 숫자로 자르지 않음", () => {
  const r = versesFromCopied("5 무리가 다 기뻐하여 6 사람을 세우니\n6 사도들 앞에 세우니", parseRef("행 6:5-6"));
  assert.deepEqual(r.map((x) => x.text), ["무리가 다 기뻐하여 6 사람을 세우니", "사도들 앞에 세우니"]);
});

test("앱 안 개역한글 + txt 성경 파일", async () => {
  const fs = await import("node:fs");
  const { versesFromBible, parseBibleTxt } = await import("../js/bible.js");
  const krv = JSON.parse(fs.readFileSync(new URL("../bible/krv.json", import.meta.url)));
  assert.equal(Object.keys(krv).length, 66);
  const r = versesFromBible(krv, parseRef("요 3:16"));
  assert.equal(r.length, 1);
  assert.match(r[0].text, /^하나님이 세상을 이처럼 사랑하사/);
  assert.equal(versesFromBible(krv, parseRef("행 6:1-7")).length, 7);
  assert.equal(versesFromBible(krv, parseRef("시 23편")).length, 6);
  assert.deepEqual(versesFromBible(krv, parseRef("롬 8:38-9:2")).map((x) => `${x.c}:${x.v}`), ["8:38", "8:39", "9:1", "9:2"]);
  const t = parseBibleTxt("창1:1 <천지 창조> 태초에 하나님이 천지를 창조하시니라\n창1:2 땅이 혼돈하고\n요한복음 3:16 하나님이 세상을\n아무 줄");
  assert.equal(t.verses, 3);
  assert.equal(t.data.gen[0][0], "태초에 하나님이 천지를 창조하시니라");
  assert.equal(versesFromBible(t.data, parseRef("요 3:16"))[0].text, "하나님이 세상을");
});

test("조금씩 모은 성경: 빠진 절이 있으면 다시 가져오게", async () => {
  const { versesFromBible, wholeChapters } = await import("../js/bible.js");
  const data = { _partial: true, _full: ["act:6"], act: [[], [], [], [], [], ["a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8"]], jhn: [[], [], ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "s16"]] };
  assert.equal(versesFromBible(data, parseRef("행 6:1-7")).length, 7);
  assert.equal(versesFromBible(data, parseRef("행 6장")).length, 8);
  assert.equal(versesFromBible(data, parseRef("요 3:16")).length, 1);
  assert.equal(versesFromBible(data, parseRef("요 3:15-16")).length, 0);
  assert.equal(versesFromBible(data, parseRef("요 3장")).length, 0);
  assert.equal(versesFromBible(data, parseRef("행 6:1-9")).length, 0);
  assert.deepEqual(wholeChapters([{ c: 6, v: 1 }, { c: 6, v: 2 }, { c: 6, v: 3 }, { c: 7, v: 2 }, { c: 7, v: 3 }]), [6]);
});
