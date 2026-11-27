// 교회 가사 모음(txt 폴더) -> 앱에 들어가는 기본 가사 보관함 lyrics/library.json
//   node church-ppt-app/tools/build-library.mjs <txt 폴더> church-ppt-app/lyrics/library.json
import fs from "fs";
import path from "path";
const L = await import(new URL("../js/lyrics.js", import.meta.url));
const [dir, out] = process.argv.slice(2);
const decode = (buf) => { try { return new TextDecoder("utf-8", { fatal: true }).decode(buf); } catch { return new TextDecoder("euc-kr").decode(buf); } };
const songs = {};
for (const f of fs.readdirSync(dir).filter((x) => /\.txt$/i.test(x)).sort()) {
  const name = f.replace(/\.txt$/i, "").replace(/txt$/i, "").replace(/_+$/, "").trim();
  const song = L.songFromAnyTxt(decode(fs.readFileSync(path.join(dir, f))), name);
  if (!song.sections.length || !song.title) continue;
  songs[song.title] = L.songToText(song);
}
const version = new Date().toISOString().slice(0, 10) + "-" + Object.keys(songs).length;
fs.writeFileSync(out, JSON.stringify({ version, songs }));
console.log(version, Object.keys(songs).length, "songs");
