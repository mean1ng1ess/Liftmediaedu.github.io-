import test from "node:test";
import assert from "node:assert/strict";
import { wordsToSong, joinSyllables } from "../js/ocr.js";

const syll = (text, y, x0 = 155) => [...text].map((ch, i) => ({ text: ch, x: x0 + i * 110, y: y + (i % 3), w: 38, h: 38 }));

test("음표 밑 글자 하나씩 -> 1절/2절/후렴", () => {
  const words = [
    { text: "은혜의", x: 700, y: 50, w: 300, h: 80 }, { text: "강가로", x: 1010, y: 50, w: 250, h: 80 },
    { text: "작사", x: 1500, y: 157, w: 50, h: 24 },
    ...syll("주님나를부르시네", 330), { text: "2.", x: 102, y: 385, w: 30, h: 34 }, ...syll("나의모든것드려요", 385),
    ...syll("은혜의강흘러가", 710), ...syll("기쁨의노래부르리", 765), ...syll("할렐루야주를찬양", 1090),
    { text: "Copyright", x: 100, y: 1409, w: 100, h: 24 },
  ].reverse();
  const s = wordsToSong([{ words, height: 1500 }]);
  assert.equal(s.title, "은혜의 강가로");
  assert.deepEqual(s.sections.map((x) => x.label), ["Verse 1", "Chorus", "Verse 2"]);
  assert.deepEqual(s.sections[0].lines, ["주님나를부르시네", "은혜의강흘러가"]);
  assert.deepEqual(s.sections[2].lines, ["나의모든것드려요", "기쁨의노래부르리"]);
  assert.deepEqual(s.order, ["Verse 1", "Chorus", "Verse 2", "Chorus"]);
});

test("붙어 있는 단어는 그대로", () => {
  assert.equal(joinSyllables([{ text: "주님의", x: 0, y: 0, w: 90, h: 30 }, { text: "사랑", x: 120, y: 0, w: 60, h: 30 }]), "주님의 사랑");
});
