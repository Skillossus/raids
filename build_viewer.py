#!/usr/bin/env python3
"""Build a static viewer for an Inventory Setups JSON export.

  python3 build_viewer.py inventory_setups.json -o out --html-name setups.html \
      --md out/converted_inventory_setups.md --ua "setup-viewer - @yourname"

Writes the viewer page (default index.html) plus icons/<id>.png (downloaded once
from the OSRS Wiki, then served locally; nothing is hotlinked) into the -o folder,
and optionally a markdown file of bank tag import strings (--md). The markdown is
written first and needs no network. Re-running skips icons that already exist.
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

MAPPING_URL = "https://prices.runescape.wiki/api/v1/osrs/mapping"
IMG_BASE = "https://oldschool.runescape.wiki/images/"
COLS, MAX_SLOTS = 8, 80  # official bank tag tab grid is 8x10


def fetch(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def load_mapping(out, ua, refresh):
    os.makedirs(os.path.join(out, "icons"), exist_ok=True)
    path = os.path.join(out, "icons", "_mapping.json")
    if os.path.exists(path) and not refresh:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = json.loads(fetch(MAPPING_URL, ua))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def import_string(layout, name):
    parts = []
    for slot, item in enumerate(layout):
        if item == -1:
            continue
        if slot >= MAX_SLOTS:
            sys.exit(f"{name}: slot {slot} is off the 8x10 grid")
        parts += [item, slot % COLS, slot // COLS]
    return f"1,{len(parts) // 3}," + ",".join(map(str, parts))


def write_markdown(setups, path):
    rows = sorted(((e["setup"]["name"], import_string(e["layout"], e["setup"]["name"]))
                   for e in setups), key=lambda r: r[0].lower())
    with open(path, "w", encoding="utf-8") as f:
        for name, s in rows:
            f.write(f"## {name}\n\n```\n{s}\n```\n\n")
    print(f"{len(rows)} setups -> {path}")


def build_records(setups, have):
    """Returns (records, used_icon_ids, unresolved {item_id: [setup names]})."""
    records, used, unresolved = [], set(), {}
    for e in setups:
        s, layout = e["setup"], e["layout"]
        layout_ids = {x for x in layout if x != -1}

        def icon_for(i):
            if i in have:
                return i
            # Layout uses canonical ids; some setup ids are canonical+1 (e.g. graceful).
            if (i - 1) in layout_ids and (i - 1) in have:
                return i - 1
            return None

        def item(it):
            if not it or it["id"] == -1:  # -1 = empty slot carrying a fuzzy flag
                return None
            c = icon_for(it["id"])
            if c is None:
                unresolved.setdefault(it["id"], []).append(s["name"])
            else:
                used.add(c)
            return {"i": it["id"], "q": it.get("q", 0), "c": c}

        afi = [item({"id": v["id"], "q": v.get("q", 0)}) for v in (s.get("afi") or {}).values()]
        records.append({
            "n": s["name"],
            "s": import_string(layout, s["name"]),
            "inv": [item(x) for x in s.get("inv") or []],
            "eq": [item(x) for x in s.get("eq") or []],
            "rp": [item(x) for x in s.get("rp") or []],
            "qv": [item(x) for x in s.get("qv") or []],
            "afi": afi,
            "notes": s.get("notes", ""),
        })
    records.sort(key=lambda r: r["n"].lower())
    return records, used, unresolved


def download_icons(used, have, out, ua):
    icon_dir = os.path.join(out, "icons")
    os.makedirs(icon_dir, exist_ok=True)
    failed = []
    for n, cid in enumerate(sorted(used), 1):
        dest = os.path.join(icon_dir, f"{cid}.png")
        if os.path.exists(dest):
            continue
        fname = have[cid]["icon"].replace(" ", "_")
        try:
            data = fetch(IMG_BASE + urllib.parse.quote(fname), ua)
            with open(dest, "wb") as f:
                f.write(data)
        except Exception as exc:  # keep going; report at the end
            failed.append((cid, have[cid]["icon"], str(exc)))
        if n % 50 == 0:
            print(f"  {n}/{len(used)} icons", flush=True)
        time.sleep(0.1)
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_file")
    ap.add_argument("-o", "--out", default="viewer")
    ap.add_argument("--ua", default="osrs-setup-viewer (personal tool)",
                    help="descriptive User-Agent; include a contact, per the wiki's API guidance")
    ap.add_argument("--html-name", default="index.html")
    ap.add_argument("--md", help="also write a markdown file of import strings here")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--refresh-mapping", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    with open(args.json_file, encoding="utf-8") as f:
        setups = json.load(f)

    if args.md:
        write_markdown(setups, args.md)

    try:
        mapping = load_mapping(args.out, args.ua, args.refresh_mapping)
    except Exception as exc:
        sys.exit(f"Could not fetch the item mapping ({exc}); no HTML written.")
    have = {m["id"]: m for m in mapping if m.get("icon")}
    records, used, unresolved = build_records(setups, have)
    names = {str(c): have[c]["name"] for c in used}

    failed = [] if args.skip_download else download_icons(used, have, args.out, args.ua)

    data = json.dumps({"setups": records, "names": names}, separators=(",", ":"))
    html = TEMPLATE.replace("__DATA__", data.replace("</", "<\\/"))
    with open(os.path.join(args.out, args.html_name), "w", encoding="utf-8") as f:
        f.write(html)

    print(f"{len(records)} setups -> {os.path.join(args.out, args.html_name)}; {len(used)} icons needed, {len(failed)} download failures")
    if unresolved:
        print(f"{len(unresolved)} item ids have no icon in the wiki mapping (shown as id text):")
        for i, who in sorted(unresolved.items(), key=lambda kv: -len(kv[1]))[:40]:
            print(f"  {i}: used in {len(who)} setup(s), e.g. {who[0]}")
    for cid, icon, err in failed[:20]:
        print(f"  download failed: {cid} {icon}: {err}")


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bank tag setups</title>
<style>
:root{--bg:#fff;--fg:#1b1b1b;--mut:#666;--card:#f4f1ea;--line:#d8d2c4;--slot:#ddd6c6;--acc:#7a5c1e}
@media (prefers-color-scheme:dark){:root{--bg:#15130f;--fg:#ece6d8;--mut:#9a927f;--card:#211e17;--line:#3a3529;--slot:#2e2a20;--acc:#d9b45a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.4 system-ui,sans-serif;padding:12px;max-width:760px;margin:auto}
h1{font-size:1.2rem;margin:.2rem 0 .6rem}
#q{width:100%;padding:12px;font-size:1rem;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
#count{color:var(--mut);font-size:.85rem;margin:.4rem 0}
details{border:1px solid var(--line);border-radius:8px;margin:6px 0;background:var(--card)}
summary{padding:12px;cursor:pointer;min-height:44px;font-weight:600}
.body{padding:0 12px 12px}
.row{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
.grid{display:grid;gap:3px;background:var(--line);padding:3px;border-radius:6px}
.inv{grid-template-columns:repeat(4,44px)}
.eq{grid-template-columns:repeat(3,44px)}
.strip{display:flex;gap:3px;flex-wrap:wrap}
.slot{position:relative;width:44px;height:40px;background:var(--slot);display:flex;align-items:center;justify-content:center;font-size:9px;color:var(--mut);overflow:hidden;border-radius:3px}
.slot.spacer{background:transparent}
.slot img{max-width:100%;max-height:100%}
.qty{position:absolute;left:2px;top:0;font:bold 11px/1 monospace;text-shadow:1px 1px #000}
h3{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:var(--acc);margin:12px 0 4px}
pre{margin:6px 0;padding:10px;background:var(--bg);border:1px solid var(--line);border-radius:6px;white-space:pre-wrap;word-break:break-all;font-size:.8rem;user-select:all}
button{padding:10px 14px;font-size:.95rem;border:1px solid var(--acc);background:transparent;color:var(--acc);border-radius:6px;min-height:44px}
.notes{white-space:pre-wrap;font-size:.9rem;color:var(--mut)}
footer{margin:24px 0 8px;color:var(--mut);font-size:.75rem}
</style></head><body>
<h1>Bank tag setups</h1>
<input id="q" type="search" placeholder="Search setups (Enter opens the first match)" autocomplete="off">
<div id="count"></div>
<div id="list"></div>
<footer>Item icons &copy; Jagex, sourced from the Old School RuneScape Wiki (CC BY-NC-SA 3.0).</footer>
<script>
const DATA = __DATA__;
const NAMES = DATA.names;
const EQ_ROWS = [[null,0,null],[1,2,13],[3,4,5],[null,7,null],[9,10,12]];

function fmt(q){
  if (q >= 1e7) return [Math.floor(q/1e6)+'M', '#00ff80'];
  if (q >= 1e5) return [Math.floor(q/1e3)+'K', '#ffffff'];
  return [String(q), '#ffff00'];
}
function el(tag, cls, text){
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function slot(it){
  const d = el('div', 'slot');
  if (!it) return d;
  d.title = (NAMES[it.c] || ('Item ' + it.i)) + (it.q > 1 ? ' x' + it.q.toLocaleString() : '');
  const fallback = () => { d.classList.add('missing'); d.append(String(it.i)); };
  if (it.c == null) fallback();
  else {
    const img = new Image();
    img.alt = ''; img.loading = 'lazy'; img.src = 'icons/' + it.c + '.png';
    img.onerror = () => { img.remove(); fallback(); };
    d.append(img);
  }
  if (it.q > 1) {
    const [t, color] = fmt(it.q);
    const s = el('span', 'qty', t); s.style.color = color; d.append(s);
  }
  return d;
}
function strip(items){
  const s = el('div', 'strip');
  items.filter(Boolean).forEach(it => s.append(slot(it)));
  return s;
}
async function copyText(text, btn){
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const t = el('textarea'); t.value = text; document.body.append(t); t.select();
    try { document.execCommand('copy'); } catch (_) {}
    t.remove();
  }
  btn.textContent = 'Copied';
  setTimeout(() => btn.textContent = 'Copy tag', 1200);
}
function render(body, s){
  const row = el('div', 'row');
  const inv = el('div'); inv.append(el('h3', null, 'Inventory'));
  const ig = el('div', 'grid inv');
  for (let i = 0; i < 28; i++) ig.append(slot((s.inv || [])[i]));
  inv.append(ig);
  const eq = el('div'); eq.append(el('h3', null, 'Equipment'));
  const eg = el('div', 'grid eq');
  EQ_ROWS.forEach(r => r.forEach(idx => {
    if (idx === null) eg.append(el('div', 'slot spacer'));
    else eg.append(slot((s.eq || [])[idx]));
  }));
  eq.append(eg);
  row.append(inv, eq);
  body.append(row);
  [['Rune pouch', s.rp], ['Quiver', s.qv], ['Additional items', s.afi]].forEach(([label, items]) => {
    if (items && items.some(Boolean)) { body.append(el('h3', null, label)); body.append(strip(items)); }
  });
  if (s.notes) { body.append(el('h3', null, 'Notes')); body.append(el('div', 'notes', s.notes)); }
  body.append(el('h3', null, 'Bank tag import string'));
  body.append(el('pre', null, s.s));
  const b = el('button', null, 'Copy tag');
  b.onclick = () => copyText(s.s, b);
  body.append(b);
}

const list = document.getElementById('list');
const q = document.getElementById('q');
const count = document.getElementById('count');
const nodes = DATA.setups.map(s => {
  const d = el('details');
  d.append(el('summary', null, s.n));
  const body = el('div', 'body');
  d.append(body);
  let done = false;
  d.addEventListener('toggle', () => {
    if (d.open && !done) { done = true; render(body, s); }
  });
  list.append(d);
  return { d, key: s.n.toLowerCase() };
});

function filter(){
  const term = q.value.trim().toLowerCase();
  let shown = 0;
  nodes.forEach(n => {
    const hit = !term || n.key.includes(term);
    n.d.hidden = !hit;
    if (hit) shown++;
  });
  count.textContent = shown + ' of ' + nodes.length + ' setups';
}
q.addEventListener('input', filter);
q.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const first = nodes.find(n => !n.d.hidden);
  if (first) { first.d.open = true; first.d.scrollIntoView({block: 'nearest'}); }
});
filter();
</script></body></html>
"""

if __name__ == "__main__":
    main()
