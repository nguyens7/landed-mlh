"""Exercise real HTTP routes against qa/mock_server.py, never a live provider server."""

import argparse
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8788")
    args = parser.parse_args()
    url = urlparse(args.base)
    if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Use a loopback HTTP URL for the isolated QA mock server.")

    def request(path, body=None, expected=200):
        data = None if body is None else json.dumps(body).encode()
        req = Request(args.base.rstrip("/") + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as response:
                status, content = response.status, response.read()
        except HTTPError as error:
            status, content = error.code, error.read()
        if status != expected:
            raise RuntimeError(f"{path}: expected {expected}, got {status}")
        return json.loads(content) if not path.startswith("/tts/") else content

    if request("/qa-mode").get("mocked_providers") is not True:
        raise RuntimeError("Refusing to run against a server without mocked providers.")

    def start(roster=None):
        request("/reset", {})
        request("/desk", {"roster": roster or ["N2646X", "N312LM", "N405LP"]})
        request("/adsb", {"reg": "N2646X", "lat": 40.7013, "lon": -74.0085, "alt_ft": 400})

    def transmission(text="check in", asr=0.95, **changes):
        body = {
            "raw_text": text,
            "asr_confidence": asr,
            "callsign": {
                "spoken": "N2646X",
                "normalized": "N2646X",
                "snapped_to": "N2646X",
                "snap_score": 0.95,
                "ambiguous_with": [],
            },
            "intent": "checkin",
            "slots": {"position": "Downtown Skyport", "altitude_ft": 500},
            "emergency": False,
            "parse_confidence": 0.97,
            "parser": "grammar",
            "reason": "QA fixture",
        }
        body.update(changes)
        return request("/transmission", body)["proposals"]

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    for run in range(1, 4):
        start()
        [routine] = transmission()
        require(routine["status"] == "auto_spoken", "Routine call did not auto-speak")
        require(request(f"/tts/{routine['id']}").startswith(b"RIFF"), "Missing WAV response")
        print(f"PASS run {run}: routine proposal and audio route (mocked silence)")

        start()
        [handoff] = request(
            "/alerts",
            [
                {
                    "id": "SIM312LM",
                    "aircraft": {"hex": "SIM312LM", "reg": "N312LM"},
                    "volume_id": "lga22_final_seg2",
                    "severity": "handoff",
                    "confidence": 0.88,
                    "reason": "QA projected path enters LGA Rwy 22 final",
                    "time_to_entry_s": 70,
                    "entry_alt_ft": 600,
                }
            ],
        )["proposals"]
        require(handoff["tier"] == "handoff", "Protected-volume event did not hand off")
        print(f"PASS run {run}: engine alert -> server handoff")

        start()
        [weather] = transmission("Losing visual in fog, request lower", slots={"weather_phrase": "fog"})
        require("weather" in weather["triggers"] and weather["tier"] == "handoff", "Weather did not hand off")
        start(["N2646X", "N2464X"])
        [retry] = transmission()
        [ambiguous] = transmission()
        require(retry["template_id"] == "SAY_AGAIN", "Ambiguity did not request clarification")
        require(
            "callsign_ambiguity" in ambiguous["triggers"] and ambiguous["tier"] == "handoff",
            "Repeated ambiguity did not hand off",
        )
        print(f"PASS run {run}: weather handoff and ambiguity retry -> handoff")

        start()
        [pending] = transmission(asr=0.75)
        require(pending["status"] == "pending", "Expected an approval card")
        decision = {"proposal_id": pending["id"], "decision": "approve", "who": "qa"}
        request("/decision", decision, expected=425)
        request(f"/tts/{pending['id']}", expected=409)
        time.sleep(1.1)
        require(request("/decision", decision)["status"] == "approved", "Armed approval failed")
        [expiring] = transmission(asr=0.75)
        time.sleep(10.2)
        request("/decision", {**decision, "proposal_id": expiring["id"]}, expected=410)
        request(f"/tts/{expiring['id']}", expected=410)
        print(f"PASS run {run}: arm delay, approval, expiry withholding")

        before = request("/state")["audit"]
        emergency = transmission("MAYDAY engine failure", intent="emergency", emergency=True)
        require(
            emergency[0]["spoken_text_preview"].endswith("controller taking over"), "Missing emergency call"
        )
        require(request("/health")["locked"], "Emergency did not lock")
        [suppressed] = transmission()
        require(
            suppressed["status"] == "suppressed" and not suppressed["spoken_text_preview"],
            "Agent spoke after emergency lock",
        )
        request(f"/tts/{suppressed['id']}", expected=409)
        request("/reset", {})
        after = request("/state")["audit"]
        require(after[: len(before)] == before and len(after) > len(before), "Reset lost prior audit records")
        print(f"PASS run {run}: emergency -> silence; audit prefix retained after reset")

    print("PASS: 3/3 deterministic HTTP runs; provider quality and latency were not tested.")


if __name__ == "__main__":
    main()
