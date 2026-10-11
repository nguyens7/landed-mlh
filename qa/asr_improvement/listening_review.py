"""Build a private, self-contained listening worksheet; never adjudicate audio automatically."""

import argparse
import base64
import hashlib
import html
import json
from pathlib import Path

from experiment import dump, load_frozen, numeric, validate_local

PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; media-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>25-clip listening review</title><style>
body{font:17px system-ui;max-width:1000px;margin:30px auto;padding:0 20px;color:#17212b;background:#f7f8fa}
article{background:white;border:1px solid #b9c4ce;border-radius:8px;padding:20px;margin:24px 0}
label{display:block;margin:12px 0}input,textarea,select,button{font:inherit;padding:8px;max-width:100%;box-sizing:border-box}
textarea{display:block;width:100%;min-height:65px}audio{width:100%}button{cursor:pointer;margin:6px}summary{cursor:pointer}
th,td{border:1px solid #bdc6cf;padding:9px;text-align:left;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}
.notice{border-left:4px solid #a45b00;padding:12px;background:#fff4df}small{display:block;color:#465464}
</style><h1>25-clip listening review</h1>
<p class="notice">No clips have been listening-adjudicated by the agent. Original gold is unchanged.
This private worksheet contains UWB noncommercial research audio and transcripts. Do not publish it.</p>
<p>Listen before revealing references or model output. Record what you hear, including repetitions and mixed languages.
Use [?] for uncertainty; never infer a number from a standard clearance or model agreement. Then reveal the comparison,
replay disputed spans, and add timestamps. Keep digit order and leading zeros; distinguish callsign letters from digits.
Only label a field type when the audio supports it. A second independent reviewer must approve proposed gold changes.</p>
<p>No network requests or automatic saving. Export your notes before closing or refreshing this page.
Playback speed controls retain pitch in supported browsers; return to 1× to verify decisions.</p>
<label>Reviewer name <input id="reviewer" autocomplete="off"></label>
<button id="export">Export review JSON</button><span id="status" role="status"></span>
__CARDS__
<script>
const records=__RECORDS__;
document.querySelectorAll('article').forEach(card=>{
 const player=card.querySelector('audio');
 card.querySelectorAll('[data-rate]').forEach(b=>b.onclick=()=>{player.playbackRate=Number(b.dataset.rate)});
 card.querySelector('[data-stamp]').onclick=()=>{
  const notes=card.querySelector('[name=evidence]');notes.value+=' ['+player.currentTime.toFixed(2)+' s] ';notes.focus();
 };
 card.querySelector('[data-reveal]').onclick=()=>{
  if(!card.querySelector('[name=heard]').checked || !card.querySelector('[name=transcript]').value.trim()){
   alert('Listen and record your independent hearing first.');return;
  }
  card.querySelector('[name=transcript]').readOnly=true;
  card.querySelector('[name=heard]').disabled=true;
  card.querySelector('[data-comparison]').hidden=false;
  card.querySelector('[data-reveal]').disabled=true;
 };
});
document.querySelector('#export').onclick=()=>{
 const reviewer=document.querySelector('#reviewer').value.trim();
 if(!reviewer){alert('Enter the reviewer name.');return;}
 const cases=Array.from(document.querySelectorAll('article')).map(card=>{
  const notes={};card.querySelectorAll('[name]').forEach(e=>notes[e.name]=e.type==='checkbox'?e.checked:e.value);
  return {id:card.dataset.id,...notes,comparison_revealed:!card.querySelector('[data-comparison]').hidden};
 });
 const complete=cases.filter(c=>c.heard&&c.transcript.trim()&&c.comparison_revealed&&c.verdict!=='pending'&&c.evidence.trim()).length;
 const output={schema_version:1,reviewer,exported_at:new Date().toISOString(),...records,
  completed_first_pass:complete,adjudication_status:'Pending independent second review; no gold changes approved',cases};
 const url=URL.createObjectURL(new Blob([JSON.stringify(output,null,2)+'\\n'],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download='uwb-listening-review.json';link.click();
 setTimeout(()=>URL.revokeObjectURL(url),1000);document.querySelector('#status').textContent=complete+'/25 first-pass cases exported';
};
</script></html>"""


def build(directory, output):
    plan, manifest, baseline = load_frozen(directory)
    if output.exists():
        raise ValueError("Use a new output path; do not overwrite a private review")
    ids = plan["audit_development"]
    by_id = {row["id"]: row for row in manifest}
    arms = {}
    for name in ("control", "literal", "segmented", "domain"):
        rows = json.loads((directory / f"audit_development-{name}.json").read_text())
        if len(rows) != len(ids) or {row["id"] for row in rows} != set(ids):
            raise ValueError("Incomplete or duplicate comparison arm")
        arms[name] = {row["id"]: row for row in rows}
    local = [json.loads(line) for line in (directory / "local-medium.jsonl").read_text().splitlines()]
    if len(local) != len({row["id"] for row in local}):
        raise ValueError("Duplicate local results")
    identity = json.loads((directory / "local-identity.json").read_text())
    selected = set(plan["audit_development"] + plan["confirmation"])
    validate_local(local, [row for row in manifest if row["id"] in selected], identity)
    arms["local_medium"] = {row["id"]: row for row in local}
    cards = []
    mismatch_counts = {name: 0 for name in ("cached_baseline", *arms)}
    for index, key in enumerate(ids, 1):
        row = by_id[key]
        reference = baseline[key]["reference"]
        comparisons = {
            "raw_reference": {"hypothesis": row["text"]},
            "normalized_reference": {"hypothesis": reference},
            "cached_baseline": baseline[key],
        }
        comparisons.update({name: rows[key] for name, rows in arms.items()})
        cells = []
        for name, result in comparisons.items():
            hypothesis = result["hypothesis"]
            numbers = numeric(hypothesis)
            if name in mismatch_counts:
                mismatch_counts[name] += bool(numeric(reference)) and numbers != numeric(reference)
            cells.append(
                "<tr><th>"
                + html.escape(name)
                + "</th><td>"
                + html.escape(hypothesis)
                + "</td><td>"
                + html.escape(json.dumps(numbers))
                + "</td><td>"
                + html.escape(str(result.get("error") or ""))
                + "</td></tr>"
            )
        encoded = base64.b64encode(Path(row["file"]).read_bytes()).decode()
        fields = "".join(
            f'<label>{title}<input name="{name}" placeholder="Unclear / not spoken" autocomplete="off"></label>'
            for name, title in (
                ("callsign", "Callsign (letters and digits)"),
                ("heading", "Heading"),
                ("altitude", "Altitude and unit"),
                ("frequency", "Frequency"),
                ("runway", "Runway"),
                ("other_numbers", "Other numbers: QNH, time, etc."),
            )
        )
        cards.append(f'''<article data-id="{html.escape(key, quote=True)}"><h2>Clip {index} of 25</h2>
<small>{html.escape(key)}</small><audio controls preload="none" src="data:audio/wav;base64,{encoded}"></audio>
<button data-rate="1">1×</button><button data-rate="0.8">0.8×</button><button data-stamp>Add current timestamp</button>
<label>Your independent hearing<textarea name="transcript"></textarea></label>
<label><input name="heard" type="checkbox"> I listened and recorded my hearing before revealing the comparison</label>
{fields}<button data-reveal>Reveal reference and model comparisons</button>
<div data-comparison hidden><table><thead><tr><th>Source</th><th>Text (raw and normalized references labeled)</th><th>Integer proxy</th><th>Error</th></tr></thead>
<tbody>{"".join(cells)}</tbody></table><p>The integer proxy misses alphanumeric callsigns and field semantics.</p></div>
<label>Reference assessment<select name="verdict"><option value="pending">Pending</option>
<option value="matches">Matches audible words</option><option value="partial_scope">Partial reference / coverage mismatch</option>
<option value="incorrect">Proposed reference correction</option><option value="uncertain">Cannot adjudicate</option></select></label>
<label>Primary explanation<select name="category"><option value="pending">Pending</option>
<option value="asr">ASR recognition error</option><option value="reference">Reference scope or error</option>
<option value="normalization">Normalization / spelling</option><option value="language">Language mismatch</option>
<option value="unclear">Unclear or mixed causes</option></select></label>
<label>Timestamped evidence and proposed correction (if any)<textarea name="evidence"></textarea></label>
</article>''')
    metadata = {
        "plan_sha256": hashlib.sha256((directory / "plan.json").read_bytes()).hexdigest(),
        "n": 25,
        "gold_unchanged": True,
        "note": "Model disagreement is triage evidence only, not auditory validation.",
    }
    rendered = PAGE.replace("__CARDS__", "\n".join(cards)).replace("__RECORDS__", json.dumps(metadata))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered)
    dump(output.with_suffix(".summary.json"), {**metadata, "integer_proxy_mismatch_cases": mismatch_counts})
    print(f"Prepared {len(ids)} private clips; zero listening judgments or provider calls.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.directory, args.output)
