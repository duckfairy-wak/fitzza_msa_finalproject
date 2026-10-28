"""Human color review between the Jev stage and indexing (4단계 사람 검수).

Jev Job이 올린 review-bundle(data/ + config/)을 받아 배포 직전 승인본까지 만드는 로컬 도구다.
AWS·Jev·모델·Qdrant를 호출하지 않는다. S3 업로드는 운영자가 따로 한다.

  page    검수 대상(review csv + 이 데이터셋에 쓰인 overrides + etc·multi)을 사진과 함께 모은 HTML을 만든다.
  apply   검수 페이지에서 저장한 review_decisions.json을 color_map.json과 reviewed_colors.json에 반영한다.
          대상이 하나라도 빠지거나 허용되지 않은 색이면 아무것도 바꾸지 않는다.
  package review_gate 승인(_APPROVED.json)과 품질 승인(_QUALITY_APPROVED.json)을 인덱서와 같은 규칙으로 확인하고
          approved/bundle.tar.gz로 올릴 파일을 만든다. 만든 파일을 다시 풀어 같은 검사를 한 번 더 한다.
"""

import argparse
import csv
import gzip
import hashlib
import html
import io
import json
from collections import defaultdict
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import tempfile

from src.review_gate import COLORS, fingerprint, verify

PALETTE_ORDER = ["black", "white", "ivory", "beige", "gray", "charcoal", "navy", "blue", "green", "khaki",
                 "brown", "red", "pink", "purple", "yellow", "orange", "multi", "etc"]
EXPECTED_PRODUCTS = 3000
MAX_MEMBERS = 30000
MAX_TOTAL_BYTES = 1024 ** 3


def dataset_colors(bundle: Path) -> dict[str, list[dict]]:
    """정규화한 color_raw별로 그 색을 쓰는 상품 예시를 모은다."""
    colors = defaultdict(list)
    for path in sorted((bundle / "data").rglob("*.json")):
        product = json.loads(path.read_text(encoding="utf-8"))
        for mapping in product.get("color_image_mappings") or []:
            raw = (mapping.get("color_raw") or "").strip()
            if raw:
                colors[raw.lower()].append({"raw": raw, "name": product.get("name", ""),
                                            "id": str(product.get("product_id")),
                                            "img": mapping.get("image_url") or ""})
    return colors


def review_reasons(bundle: Path, color_map: dict, colors: dict) -> dict[str, list[str]]:
    """review_gate.fingerprint가 사람 검수를 요구하는 색상과 그 이유."""
    reasons = defaultdict(list)
    with (bundle / "config/color_map_review.csv").open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            reasons[row["color_raw"].strip().lower()].append("Jev 확신 낮음 또는 etc·multi")
    overrides_path = bundle / "config/color_map_overrides.json"
    if overrides_path.exists():
        for key in json.loads(overrides_path.read_text(encoding="utf-8")):
            normalized = key.strip().lower()
            if not key.startswith("_") and normalized in colors:
                reasons[normalized].append("사람이 정한 값(overrides) 재확인")
    for key in colors:
        if color_map.get(key) in ("etc", "multi") and not reasons[key]:
            reasons[key].append(f"현재 {color_map[key]}")
    return {key: value for key, value in reasons.items() if value}


def build_page(bundle: Path) -> Path:
    color_map = json.loads((bundle / "config/color_map.json").read_text(encoding="utf-8"))
    colors = dataset_colors(bundle)
    jev = {}
    results = bundle / "config/color_map_jev_results.jsonl"
    if results.exists():
        for line in results.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                jev[record["key"]] = record
    items = []
    reasons = review_reasons(bundle, color_map, colors)
    for key in sorted(reasons, key=lambda k: (jev.get(k, {}).get("confidence", 1.0), k)):
        if key not in colors:
            continue
        record = jev.get(key, {})
        examples = colors[key]
        items.append({"key": key, "raw": examples[0]["raw"], "reasons": reasons[key],
                      "current": color_map.get(key, "etc"), "jev": record.get("choice"),
                      "conf": record.get("confidence"), "top3": record.get("top3") or [],
                      "count": len({example["id"] for example in examples}), "examples": examples[:3]})
    page = (TEMPLATE.replace("__DATA__", json.dumps(items, ensure_ascii=False).replace("</", "<\\/"))
            .replace("__COLORS__", json.dumps(PALETTE_ORDER)).replace("__TITLE__", html.escape(bundle.name)))
    output = bundle.parent / f"{bundle.name}-color-review.html"
    output.write_text(page, encoding="utf-8")
    print(f"검수 대상 {len(items)}개 -> {output}")
    return output


def apply_decisions(bundle: Path, decisions_path: Path) -> dict:
    if (bundle / "config/_APPROVED.json").exists():
        raise ValueError("이미 승인된 번들입니다(_APPROVED.json). 새로 받은 번들에서 다시 검수하세요.")
    map_path = bundle / "config/color_map.json"
    color_map = json.loads(map_path.read_text(encoding="utf-8"))
    decisions = {key.strip().lower(): value
                 for key, value in json.loads(decisions_path.read_text(encoding="utf-8")).items()}
    colors = dataset_colors(bundle)
    required = set(review_reasons(bundle, color_map, colors)) & colors.keys()
    missing = sorted(required - decisions.keys())
    invalid = {key: value for key, value in decisions.items() if value not in COLORS}
    unknown = sorted(decisions.keys() - colors.keys())
    if missing or invalid or unknown:
        problems = []
        if missing:
            problems.append(f"확인 안 된 검수 대상 {len(missing)}개: {', '.join(missing[:10])}")
        if invalid:
            problems.append(f"허용되지 않은 색상 값: {invalid}")
        if unknown:
            problems.append(f"이 데이터셋에 없는 색상 이름: {', '.join(unknown[:10])}")
        raise ValueError("; ".join(problems) + " (아무것도 바꾸지 않았습니다)")
    changed = {key: (color_map.get(key), value) for key, value in decisions.items() if color_map.get(key) != value}
    color_map.update(decisions)
    map_path.write_text(json.dumps(color_map, ensure_ascii=False, indent=4), encoding="utf-8")
    (bundle / "config/reviewed_colors.json").write_text(
        json.dumps(dict(sorted(decisions.items())), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"검수 {len(decisions)}개 반영, 값이 바뀐 것 {len(changed)}개")
    for key, (old, new) in sorted(changed.items()):
        print(f"  {key}: {old} -> {new}")
    return changed


def check_deployable(bundle: Path, require_quality: bool) -> dict:
    """indexer/entrypoint.py가 Qdrant 연결 전에 하는 검사와 같은 검사."""
    verify(bundle)
    current = fingerprint(bundle)
    if current["product_count"] != EXPECTED_PRODUCTS:
        raise ValueError(f"승인 상품이 {current['product_count']}개입니다(인덱서는 {EXPECTED_PRODUCTS}개 필요)")
    quality_path = bundle / "config/_QUALITY_APPROVED.json"
    if not quality_path.exists():
        if require_quality:
            raise ValueError("품질 승인(config/_QUALITY_APPROVED.json)이 없습니다. 인덱서는 이 파일 없이 실패합니다.")
        return {**current, "quality_approved": False}
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    if quality.get("approved") is not True or quality.get("files") != current["files"]:
        raise ValueError("품질 승인이 없거나 승인 뒤 번들이 바뀌었습니다")
    if not re.fullmatch(r"[a-f0-9]{40}", quality.get("model_revision", "")):
        raise ValueError("품질 승인에 FashionCLIP 모델 commit SHA(40자리)가 없습니다")
    return {**current, "quality_approved": True}


def _add(archive: tarfile.TarFile, path: Path, name: str) -> None:
    info = tarfile.TarInfo(name)
    if path.is_dir():
        info.type, info.mode = tarfile.DIRTYPE, 0o755
        archive.addfile(info)
        return
    data = path.read_bytes()
    info.size, info.mode = len(data), 0o644
    archive.addfile(info, io.BytesIO(data))


def write_archive(bundle: Path, output: Path) -> None:
    """data/와 config/만 담는다. 시각·소유자를 고정해 같은 번들이면 같은 파일이 나온다."""
    paths = []
    for top in ("config", "data"):
        root = bundle / top
        paths.append(root)
        paths.extend(sorted(root.rglob("*")))
    if any(path.is_symlink() for path in paths):
        raise ValueError("번들에 심볼릭 링크가 있습니다")
    with output.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed, \
            tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in paths:
            _add(archive, path, path.relative_to(bundle).as_posix())


def unpack_like_indexer(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as source:
        members = source.getmembers()
        if len(members) > MAX_MEMBERS or sum(member.size for member in members) > MAX_TOTAL_BYTES:
            raise ValueError("Bundle exceeds limits")
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or "\\" in member.name or ":" in member.name
                    or not (member.isfile() or member.isdir())):
                raise ValueError("Unsafe bundle member")
        source.extractall(destination, members=members, filter="data")


def package(bundle: Path, output: Path, require_quality: bool) -> dict:
    status = check_deployable(bundle, require_quality)
    write_archive(bundle, output)
    with tempfile.TemporaryDirectory() as folder:
        unpacked = Path(folder)
        unpack_like_indexer(output, unpacked)
        recheck = check_deployable(unpacked, require_quality)
    if recheck["files"] != status["files"]:
        raise ValueError("압축한 번들이 원본과 다릅니다")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    summary = {"output": str(output), "sha256": digest, "products": status["product_count"],
               "unique_colors": status["unique_color_count"], "reviewed": status["required_review_count"],
               "quality_approved": status["quality_approved"]}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not status["quality_approved"]:
        print("색상 승인만 된 번들입니다. 품질 승인(_QUALITY_APPROVED.json)을 추가한 뒤 --require-quality로 다시 만들어야 인덱싱할 수 있습니다.")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    page_parser = commands.add_parser("page")
    page_parser.add_argument("--bundle", type=Path, required=True)
    apply_parser = commands.add_parser("apply")
    apply_parser.add_argument("--bundle", type=Path, required=True)
    apply_parser.add_argument("--decisions", type=Path, required=True)
    package_parser = commands.add_parser("package")
    package_parser.add_argument("--bundle", type=Path, required=True)
    package_parser.add_argument("--output", type=Path, required=True)
    package_parser.add_argument("--require-quality", action="store_true",
                                help="품질 승인까지 확인한다(인덱서에 넘길 최종본)")
    args = parser.parse_args()
    try:
        if args.command == "page":
            build_page(args.bundle)
        elif args.command == "apply":
            apply_decisions(args.bundle, args.decisions)
        else:
            package(args.bundle, args.output, args.require_quality)
    except (ValueError, FileExistsError) as error:
        sys.exit(f"[실패] {error}")


TEMPLATE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>색상 검수</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1f2937;--mute:#6b7280;--line:#e5e7eb;--ok:#15803d;--warn:#b45309;--accent:#2563eb}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1e;--ink:#e5e7eb;--mute:#9ca3af;--line:#333;--ok:#4ade80;--warn:#fbbf24;--accent:#60a5fa}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
h1{font-size:16px;margin:0 12px 0 0}.bar{flex:1;min-width:160px;height:8px;background:var(--line);border-radius:4px;overflow:hidden}.bar i{display:block;height:100%;background:var(--ok);width:0}
button,select,input[type=search]{font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:6px 10px}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
main{padding:12px 16px;display:grid;gap:10px;max-width:1100px;margin:0 auto}
.row{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;display:grid;grid-template-columns:240px 1fr 190px;gap:12px;align-items:start}
.row.done{border-color:var(--ok)}.imgs{display:flex;gap:6px}.imgs a{flex:1}.imgs img{width:100%;aspect-ratio:1;object-fit:cover;border-radius:6px;background:var(--line)}
.raw{font-size:16px;font-weight:700}.mute{color:var(--mute);font-size:12px}.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:9px;border:1px solid var(--warn);color:var(--warn);margin:2px 4px 0 0}
.pick{display:grid;gap:8px}.pick label{display:flex;gap:6px;align-items:center}
@media (max-width:760px){.row{grid-template-columns:1fr}}
</style></head><body>
<header><h1>색상 검수 · __TITLE__</h1><span id="count"></span><div class="bar"><i id="prog"></i></div>
<input type="search" id="q" placeholder="색상 이름 검색"><label><input type="checkbox" id="todo"> 미확인만</label>
<button id="save" class="primary">결과 저장(review_decisions.json)</button></header>
<main id="list"></main>
<script>
const ITEMS=__DATA__, COLORS=__COLORS__, STORE="jev-color-review:__TITLE__";
let state={};try{state=JSON.parse(localStorage.getItem(STORE)||"{}")}catch(e){}
const persist=()=>{try{localStorage.setItem(STORE,JSON.stringify(state))}catch(e){}};
const list=document.getElementById("list");
function render(){
  const q=document.getElementById("q").value.trim().toLowerCase(), todo=document.getElementById("todo").checked;
  list.textContent="";
  for(const it of ITEMS){
    const s=state[it.key]||{color:it.current,checked:false};
    if(q&&!it.key.includes(q))continue; if(todo&&s.checked)continue;
    const row=document.createElement("div");row.className="row"+(s.checked?" done":"");
    const imgs=document.createElement("div");imgs.className="imgs";
    for(const ex of it.examples){if(!/^https?:/.test(ex.img))continue;const a=document.createElement("a");a.href=ex.img;a.target="_blank";const im=document.createElement("img");im.loading="lazy";im.src=ex.img;im.alt=ex.name;a.append(im);imgs.append(a)}
    const info=document.createElement("div");
    const raw=document.createElement("div");raw.className="raw";raw.textContent=it.raw;info.append(raw);
    for(const r of it.reasons){const t=document.createElement("span");t.className="tag";t.textContent=r;info.append(t)}
    const j=document.createElement("div");j.className="mute";
    j.textContent=(it.jev?`Jev: ${it.jev} (${(it.conf??0).toFixed(2)}) · 후보 ${it.top3.map(t=>t[0]+" "+Number(t[1]).toFixed(2)).join(", ")} · `:"")+`현재 매핑: ${it.current} · 상품 ${it.count}개`;info.append(j);
    for(const ex of it.examples){const n=document.createElement("div");n.className="mute";n.textContent=`#${ex.id} ${ex.name}`;info.append(n)}
    const pick=document.createElement("div");pick.className="pick";
    const sel=document.createElement("select");for(const c of COLORS){const o=document.createElement("option");o.value=c;o.textContent=c;sel.append(o)}sel.value=s.color;
    const lab=document.createElement("label");const cb=document.createElement("input");cb.type="checkbox";cb.checked=s.checked;lab.append(cb," 확인함");
    const upd=()=>{state[it.key]={color:sel.value,checked:cb.checked};persist();row.className="row"+(cb.checked?" done":"");progress()};
    sel.onchange=()=>{cb.checked=true;upd()};cb.onchange=upd;
    pick.append(sel,lab);row.append(imgs,info,pick);list.append(row);
  }
  progress();
}
function progress(){const done=ITEMS.filter(it=>state[it.key]?.checked).length;document.getElementById("count").textContent=`${done} / ${ITEMS.length} 확인`;document.getElementById("prog").style.width=(100*done/ITEMS.length)+"%"}
document.getElementById("q").oninput=render;document.getElementById("todo").onchange=render;
document.getElementById("save").onclick=()=>{
  const left=ITEMS.filter(it=>!state[it.key]?.checked).length;
  if(left&&!confirm(`아직 ${left}개를 확인하지 않았어요. 확인한 것만 저장할까요? (적용 스크립트는 전부 확인해야 통과해요)`))return;
  const out={};for(const it of ITEMS){const s=state[it.key];if(s?.checked)out[it.key]=s.color}
  const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(out,null,1)],{type:"application/json"}));a.download="review_decisions.json";a.click();
};
render();
</script></body></html>"""


if __name__ == "__main__":
    main()
