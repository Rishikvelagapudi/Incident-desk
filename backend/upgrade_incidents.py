import json
import re
from pathlib import Path
from agents import ReportingAgent

def upgrade():
    p = Path(__file__).parent / "data" / "incidents.json"
    if not p.is_file():
        print("No incidents.json found")
        return
    data = json.loads(p.read_text())
    agent = ReportingAgent()
    
    for inc in data:
        ev_dummy = {"detail": inc.get("detail", "")}
        total = len(inc.get("evidence", []))
        for idx, fr in enumerate(inc.get("evidence", [])):
            txt = fr.get("finding", "")
            vehs_m = re.search(r"(\d+)\s+vehicle", txt)
            pers_m = re.search(r"(\d+)\s+person", txt)
            vehs = int(vehs_m.group(1)) if vehs_m else None
            pers = int(pers_m.group(1)) if pers_m else None
            
            f = {
                "t": fr.get("video_ts", 0.0),
                "summary": {
                    "vehicles": vehs,
                    "persons": pers,
                    "objects": []
                }
            }
            exp = agent.explain_frame(inc, ev_dummy, fr.get("phase", "event"), f, idx + 1, total)
            fr["title"] = exp["title"]
            fr["phase_label"] = exp["phase_label"]
            fr["delta_t"] = exp["delta_t"]
            fr["delta_t_text"] = exp["delta_t_text"]
            fr["finding"] = exp["finding"]
            fr["scene_context"] = exp["scene_context"]
            fr["tracked_entities"] = exp["tracked_entities"]
            fr["dynamics"] = exp["dynamics"]
            fr["operator_note"] = exp["operator_note"]
    
    p.write_text(json.dumps(data, indent=2))
    print(f"Upgraded {len(data)} incidents in {p}")

if __name__ == "__main__":
    upgrade()
