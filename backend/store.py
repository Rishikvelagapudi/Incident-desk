"""In-memory store with JSON persistence and an optional MongoDB mirror (set MONGO_URL)."""
import json
import logging
import shutil
import threading
from datetime import datetime

from config import DATA_DIR, EVIDENCE_DIR, MONGO_URL, UPLOAD_DIR

log = logging.getLogger("store")


class Store:
    def __init__(self):
        self.cameras: dict[str, dict] = {}
        self.paths: dict[str, str] = {}
        self.incidents: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._file = DATA_DIR / "incidents.json"
        self._col = None
        if self._file.is_file():
            try:
                for item in json.loads(self._file.read_text()):
                    self.incidents[item["id"]] = item
                    cam_id = item.get("camera_id")
                    vref = item.get("video_ref") or {}
                    fname = vref.get("file")
                    if cam_id and fname and cam_id not in self.paths:
                        for p in UPLOAD_DIR.iterdir():
                            if p.name.endswith(fname) or fname in p.name:
                                self.paths[cam_id] = str(p)
                                self.cameras[cam_id] = dict(
                                    id=cam_id,
                                    name=item.get("camera_name", cam_id),
                                    file=fname,
                                    video_sha256=vref.get("sha256"),
                                    status="complete",
                                    progress=1.0,
                                    video_ts=item.get("video_ts", 0.0),
                                    video_url=f"/api/videos/{cam_id}",
                                    severity="normal",
                                    incident_count=1,
                                    error=None,
                                )
                                break
            except Exception as exc:  # noqa: BLE001
                log.warning("Could not restore incidents from disk: %s", exc)
        if MONGO_URL:
            try:
                from pymongo import MongoClient

                self._col = MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000)["incident_desk"]["incidents"]
            except Exception as exc:  # noqa: BLE001
                log.warning("MongoDB mirror disabled: %s", exc)

    def next_id(self) -> str:
        with self._lock:
            return f"INC-{datetime.now().year}-{len(self.incidents) + 1:03d}"

    def add_incident(self, inc: dict):
        self.incidents[inc["id"]] = inc
        self.save_incident(inc)

    def save_incident(self, inc: dict):
        with self._lock:
            self._file.write_text(json.dumps(list(self.incidents.values()), indent=2))
        if self._col is not None:
            try:
                self._col.replace_one({"id": inc["id"]}, inc, upsert=True)
            except Exception as exc:  # noqa: BLE001
                log.warning("MongoDB write failed: %s", exc)

    def incidents_for(self, cam_id: str) -> list[dict]:
        return [i for i in self.incidents.values() if i["camera_id"] == cam_id]

    def clear(self):
        self.cameras.clear()
        self.paths.clear()
        self.incidents.clear()
        self._file.write_text("[]")
        for d in EVIDENCE_DIR.iterdir():
            shutil.rmtree(d, ignore_errors=True)
