"""Write hmi_ui/src/lib/plantTags.generated.js from incident_catalog.py.

Run:  python tools/gen_frontend_tags.py
tests/test_six_incidents.py fails if the committed file is out of date.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
OUT = HERE.parent / "hmi_ui" / "src" / "lib" / "plantTags.generated.js"


def render() -> str:
    import incident_catalog as c
    eq = {}
    for tag, s in c.plant_signals().items():
        eq.setdefault(s.equipment_id, []).append({"tag": tag, "label": s.label, "unit": s.unit})
    tag_eq = {t: s.equipment_id for t, s in c.plant_signals().items()}
    tag_eq.update({t: s.equipment_id for t, s in c.plant_statuses().items()})
    for t, info in c.alarm_inputs().items():
        tag_eq.setdefault(t, info["equipment_id"])
    labels = {t: info["label"] for t, info in c.alarm_inputs().items()}
    labels.update({t: s.label for t, s in c.plant_statuses().items()})
    return ("// Generated from edge_intelligence/incident_catalog.py by tools/gen_frontend_tags.py.\n"
            "// Do not edit by hand.\n"
            f"export const PLANT_EQUIPMENT_TAGS = {json.dumps(eq, ensure_ascii=False, indent=1)};\n"
            f"export const TAG_EQUIPMENT = {json.dumps(tag_eq, ensure_ascii=False, indent=1)};\n"
            f"export const ALARM_LABELS = {json.dumps(labels, ensure_ascii=False, indent=1)};\n")


if __name__ == "__main__":
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT}")
