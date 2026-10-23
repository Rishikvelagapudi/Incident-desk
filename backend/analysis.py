"""Video Analysis Agent: sampled-frame detection plus rule-based incident heuristics.

Everything here describes *possible* events. Rules look at bounding-box geometry and
motion only, so the wording downstream must stay hedged and operator-verified.
"""
from __future__ import annotations

import logging
import math
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from itertools import combinations

import cv2
import numpy as np

from config import (CONGESTION_MIN, EVENT_COOLDOWN_SEC, EVIDENCE_POST_SEC, EVIDENCE_PRE_SEC,
                    SAMPLE_FPS, SEGMENT_SEC, YOLO_CONF, YOLO_MODEL)

log = logging.getLogger("analysis")

PERSON = 0
VEHICLES = {2, 3, 5, 7}  # car, motorcycle, bus, truck (COCO ids)
NAMES = {0: "person", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def fmt_ts(sec: float) -> str:
    s = int(sec)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


@dataclass
class Det:
    cls: int
    box: tuple
    conf: float


def iou(a, b) -> float:
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


class Detector:
    """One shared YOLOv8 model, guarded by a lock so camera threads can share it."""

    _model = None
    _tried = False
    _lock = threading.Lock()

    @classmethod
    def model(cls):
        with cls._lock:
            if not cls._tried:
                cls._tried = True
                try:
                    from ultralytics import YOLO

                    cls._model = YOLO(YOLO_MODEL)
                except Exception as exc:  # noqa: BLE001
                    log.warning("YOLO unavailable (%s); using motion-only analysis", exc)
        return cls._model

    @classmethod
    def detect(cls, frame):
        m = cls.model()
        if m is None:
            return None
        with cls._lock:
            res = m.predict(frame, conf=YOLO_CONF, verbose=False, imgsz=640)[0]
        out = []
        for b in res.boxes:
            c = int(b.cls[0])
            if c == PERSON or c in VEHICLES:
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
                out.append(Det(c, (x1, y1, x2, y2), float(b.conf[0])))
        return out


class Track:
    def __init__(self, tid, cls, box, t):
        self.id, self.cls, self.first_t = tid, cls, t
        self.hist = [(t, box)]
        self.missed = 0
        self.zone_since = None
        self.zone_fired = False

    @property
    def box(self):
        return self.hist[-1][1]

    def add(self, t, box):
        self.hist.append((t, box))
        del self.hist[:-60]
        self.missed = 0

    def at(self, t):
        return min(self.hist, key=lambda e: abs(e[0] - t))

    def speed(self, t0, t1, diag):
        """Centre displacement in frame-diagonals per second between two times."""
        a, b = self.at(t0), self.at(t1)
        dt = b[0] - a[0]
        if dt < 0.2:
            return 0.0
        return math.dist(center(a[1]), center(b[1])) / dt / diag


class Tracker:
    def __init__(self):
        self.tracks: dict[int, Track] = {}
        self.next_id = 1

    def update(self, dets, t):
        free = list(dets)
        for tr in list(self.tracks.values()):
            best, best_d = None, 1e9
            tw, th = tr.box[2] - tr.box[0], tr.box[3] - tr.box[1]
            for d in free:
                if d.cls != tr.cls:
                    continue
                dist = math.dist(center(tr.box), center(d.box))
                if (iou(tr.box, d.box) > 0.1 or dist < 0.6 * max(tw, th)) and dist < best_d:
                    best, best_d = d, dist
            if best:
                tr.add(t, best.box)
                free.remove(best)
            else:
                tr.missed += 1
        for d in free:
            self.tracks[self.next_id] = Track(self.next_id, d.cls, d.box, t)
            self.next_id += 1
        for tid in [k for k, v in self.tracks.items() if v.missed > 5]:
            del self.tracks[tid]
        return list(self.tracks.values())


class RuleEngine:
    """Turns tracks into candidate events: collision, fall, restricted-zone entry."""

    def __init__(self, zone=None):
        self.tracker = Tracker()
        self.zone = zone
        self.summary = dict(vehicles=None, persons=None, conf=None)
        self.cong_since, self.cong_fired = None, False

    def step(self, dets, t, shape):
        h, w = shape
        diag = math.hypot(w, h)
        tracks = [tr for tr in self.tracker.update(dets, t) if tr.missed == 0]
        
        tracked_objects = []
        for tr in tracks:
            cx, cy = center(tr.box)
            pos_x = "left" if cx < w * 0.38 else "right" if cx > w * 0.62 else "center"
            pos_y = "top" if cy < h * 0.38 else "bottom" if cy > h * 0.62 else "middle"
            loc = f"{pos_y}-{pos_x}"
            spd = tr.speed(t - 1.0, t, diag) if t - tr.first_t >= 0.5 else 0.0
            spd_lbl = "stationary" if spd < 0.02 else "slow" if spd < 0.08 else "moderate" if spd < 0.18 else "fast"
            obj_data = dict(
                id=tr.id, cls=tr.cls, name=NAMES.get(tr.cls, "object"), loc=loc,
                speed=round(spd, 3), speed_label=spd_lbl, box=[round(float(v), 1) for v in tr.box],
            )
            if tr.cls == PERSON:
                bw, bh = tr.box[2] - tr.box[0], tr.box[3] - tr.box[1]
                ar = bw / max(1.0, bh)
                obj_data["aspect_ratio"] = round(ar, 2)
                obj_data["posture"] = "upright standing" if ar < 0.75 else "stooped/bending" if ar < 1.1 else "horizontal/fallen"
            if self.zone:
                x1, y1, x2, y2 = self.zone
                fx, fy = cx / w, tr.box[3] / h
                obj_data["in_zone"] = bool(x1 <= fx <= x2 and y1 <= fy <= y2)
            tracked_objects.append(obj_data)

        self.summary = dict(
            vehicles=sum(tr.cls in VEHICLES for tr in tracks),
            persons=sum(tr.cls == PERSON for tr in tracks),
            conf=round(float(np.mean([d.conf for d in dets])), 2) if dets else None,
            objects=tracked_objects,
            tracks_count=len(tracks),
            diag=round(diag, 1),
            shape=[h, w],
        )
        events = []

        vehicles = [tr for tr in tracks if tr.cls in VEHICLES and t - tr.first_t >= 1.0]
        for a, b in combinations(vehicles, 2):
            ov = iou(a.box, b.box)
            if ov < 0.08:
                continue
            drop = False
            a_before, a_now = a.speed(t - 1.6, t - 0.6, diag), a.speed(t - 0.6, t, diag)
            b_before, b_now = b.speed(t - 1.6, t - 0.6, diag), b.speed(t - 0.6, t, diag)
            a_decel = max(0.0, (a_before - a_now) / max(1e-4, a_before) * 100.0) if a_before > 0.05 else 0.0
            b_decel = max(0.0, (b_before - b_now) / max(1e-4, b_before) * 100.0) if b_before > 0.05 else 0.0

            if (a_before > 0.08 and a_now < 0.4 * a_before) or (b_before > 0.08 and b_now < 0.4 * b_before):
                drop = True
            if drop:
                max_decel = max(a_decel, b_decel)
                decel_tr = a if a_decel >= b_decel else b
                events.append(
                    dict(
                        type="collision", t=t, confidence=min(0.95, 0.58 + ov),
                        boxes=[(a.box, NAMES[a.cls]), (b.box, NAMES[b.cls])],
                        detail=(f"Vehicular collision: {NAMES[a.cls]} #{a.id} and {NAMES[b.cls]} #{b.id} collided with spatial overlap IoU={ov:.2f}. "
                                f"{NAMES[decel_tr.cls]} #{decel_tr.id} decelerated sharply by {max_decel:.0f}% immediately upon impact."),
                        meta=dict(
                            a_id=a.id, b_id=b.id, a_cls=NAMES[a.cls], b_cls=NAMES[b.cls],
                            iou=round(ov, 3), a_decel_pct=round(a_decel, 1), b_decel_pct=round(b_decel, 1),
                            a_speed_before=round(a_before, 3), a_speed_now=round(a_now, 3),
                            b_speed_before=round(b_before, 3), b_speed_now=round(b_now, 3),
                            max_decel_pct=round(max_decel, 1),
                        ),
                    )
                )

        # Check vehicle-to-pedestrian collision hazards
        persons = [tr for tr in tracks if tr.cls == PERSON and t - tr.first_t >= 0.8]
        for v in vehicles:
            for p in persons:
                ov_vp = iou(v.box, p.box)
                if ov_vp < 0.05:
                    continue
                v_before, v_now = v.speed(t - 1.6, t - 0.6, diag), v.speed(t - 0.6, t, diag)
                if v_before > 0.08 and v_now < 0.45 * v_before:
                    v_decel = max(0.0, (v_before - v_now) / max(1e-4, v_before) * 100.0)
                    events.append(
                        dict(
                            type="collision", t=t, confidence=min(0.95, 0.65 + ov_vp),
                            boxes=[(v.box, NAMES[v.cls]), (p.box, "person")],
                            detail=(f"Vehicle-pedestrian collision hazard: {NAMES[v.cls]} #{v.id} collided with Person #{p.id} (IoU={ov_vp:.2f}). "
                                    f"Vehicle velocity collapsed by {v_decel:.0f}% with immediate pedestrian obstruction."),
                            meta=dict(
                                a_id=v.id, b_id=p.id, a_cls=NAMES[v.cls], b_cls="person",
                                iou=round(ov_vp, 3), a_decel_pct=round(v_decel, 1), b_decel_pct=0.0,
                                a_speed_before=round(v_before, 3), a_speed_now=round(v_now, 3),
                                max_decel_pct=round(v_decel, 1),
                                subtype="vehicle_pedestrian",
                            ),
                        )
                    )

        for tr in tracks:
            if tr.cls != PERSON:
                continue
            bw, bh = tr.box[2] - tr.box[0], tr.box[3] - tr.box[1]
            if t - tr.first_t >= 1.5 and bh > 0:
                past = [e for e in tr.hist if t - 2.0 <= e[0] <= t - 0.8]
                if len(past) >= 2:
                    ars = [(e[1][2] - e[1][0]) / max(1.0, e[1][3] - e[1][1]) for e in past]
                    hs = [e[1][3] - e[1][1] for e in past]
                    mean_ar = float(np.mean(ars))
                    mean_h = float(np.mean(hs))
                    cur_ar = bw / max(1.0, bh)
                    drop_pct = (1.0 - bh / max(1.0, mean_h)) * 100.0
                    if mean_ar < 0.9 and cur_ar > 1.1 and bh < 0.75 * mean_h:
                        events.append(
                            dict(
                                type="fall", t=t, confidence=min(0.90, 0.60 + min(0.3, drop_pct / 200.0)),
                                boxes=[(tr.box, "person")],
                                detail=(f"Pedestrian fall: Person #{tr.id} collapsed from upright posture (aspect ratio {mean_ar:.2f}, height {int(mean_h)}px) "
                                        f"to ground level (aspect ratio {cur_ar:.2f}, height {int(bh)}px), representing a {drop_pct:.0f}% vertical collapse."),
                                meta=dict(
                                    person_id=tr.id, baseline_aspect_ratio=round(mean_ar, 2),
                                    fallen_aspect_ratio=round(cur_ar, 2), baseline_height=round(mean_h, 1),
                                    fallen_height=round(bh, 1), height_drop_pct=round(drop_pct, 1),
                                ),
                            )
                        )
            if self.zone:
                x1, y1, x2, y2 = self.zone
                fx, fy = (tr.box[0] + tr.box[2]) / 2 / w, tr.box[3] / h
                if x1 <= fx <= x2 and y1 <= fy <= y2:
                    tr.zone_since = tr.zone_since if tr.zone_since is not None else t
                    if t - tr.zone_since >= 1.0 and not tr.zone_fired:
                        tr.zone_fired = True
                        dwell = round(t - tr.zone_since, 1)
                        events.append(
                            dict(
                                type="restricted_zone", t=t, confidence=0.75,
                                boxes=[(tr.box, "person")],
                                detail=(f"Unauthorized perimeter entry: Person #{tr.id} crossed restricted boundary [{x1:.2f}, {y1:.2f}, {x2:.2f}, {y2:.2f}] "
                                        f"and sustained continuous presence for {dwell:.1f}s."),
                                meta=dict(person_id=tr.id, zone=list(self.zone), dwell_sec=dwell),
                            )
                        )
                else:
                    tr.zone_since = None

        veh_all = [tr for tr in tracks if tr.cls in VEHICLES]
        slow = [tr for tr in veh_all if tr.speed(t - 1.5, t, diag) < 0.02]
        if len(veh_all) >= CONGESTION_MIN and len(slow) >= 0.8 * len(veh_all):
            self.cong_since = t if self.cong_since is None else self.cong_since
            if t - self.cong_since >= 4.0 and not self.cong_fired:
                self.cong_fired = True
                pct = int(len(slow) / max(1, len(veh_all)) * 100)
                events.append(
                    dict(
                        type="congestion", t=t, confidence=0.70, boxes=[(tr.box, NAMES[tr.cls]) for tr in slow[:12]],
                        detail=(f"Corridor congestion: {len(slow)} of {len(veh_all)} tracked vehicles ({pct}%) "
                                "are immobilized (<0.02 diag/s) for over 4.0s, creating roadway queue blockage."),
                        meta=dict(slow_count=len(slow), total_vehicles=len(veh_all), congestion_pct=pct),
                    )
                )
        else:
            self.cong_since, self.cong_fired = None, False
        return events


class MotionMonitor:
    """Detector-independent fallback: flags sudden, sustained frame-wide change."""

    def __init__(self):
        self.prev, self.base, self.hot = None, 0.01, 0

    def update(self, frame, t):
        g = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY), (5, 5), 0)
        if self.prev is None:
            self.prev = g
            return None
        diff = cv2.absdiff(g, self.prev)
        frac = float((diff > 25).mean())
        self.prev = g
        surge = frac > 0.12 and frac > 4 * self.base
        self.hot = self.hot + 1 if surge else 0
        if not surge:
            self.base = 0.95 * self.base + 0.05 * frac
        if self.hot >= 2:
            self.hot = 0
            # Identify bounding box of the primary motion disturbance
            boxes = []
            try:
                _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if contours:
                    c = max(contours, key=cv2.contourArea)
                    cx, cy, cw, ch = cv2.boundingRect(c)
                    orig_h, orig_w = frame.shape[:2]
                    sx, sy = orig_w / 160.0, orig_h / 90.0
                    boxes = [((cx * sx, cy * sy, (cx + cw) * sx, (cy + ch) * sy), "motion disturbance")]
            except Exception:
                pass
            return dict(
                type="motion_surge", t=t, confidence=min(0.85, 0.45 + frac), boxes=boxes,
                detail=f"Abnormal motion surge: {frac * 100:.1f}% of frame experienced abrupt pixel variance, well above baseline.",
            )
        return None


def draw_tactical_box(img, box, color, label=None, is_critical=False):
    x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
    h, w = img.shape[:2]
    x1, x2 = max(0, min(w - 1, x1)), max(0, min(w - 1, x2))
    y1, y2 = max(0, min(h - 1, y1)), max(0, min(h - 1, y2))
    if x2 <= x1 or y2 <= y1:
        return

    thick = 2 if is_critical else 1
    if is_critical and y2 > y1 and x2 > x1:
        sub = img[y1:y2, x1:x2]
        if sub.size > 0:
            red_overlay = np.full_like(sub, (20, 20, 195), dtype=np.uint8)
            cv2.addWeighted(red_overlay, 0.22, sub, 0.78, 0, sub)
            img[y1:y2, x1:x2] = sub

    cv2.rectangle(img, (x1, y1), (x2, y2), color, thick)
    clen = min(16, max(5, min(x2 - x1, y2 - y1) // 3))
    bracket_color = (0, 0, 255) if is_critical else color
    bthick = thick + 1
    cv2.line(img, (x1, y1), (x1 + clen, y1), bracket_color, bthick)
    cv2.line(img, (x1, y1), (x1, y1 + clen), bracket_color, bthick)
    cv2.line(img, (x2, y1), (x2 - clen, y1), bracket_color, bthick)
    cv2.line(img, (x2, y1), (x2, y1 + clen), bracket_color, bthick)
    cv2.line(img, (x1, y2), (x1 + clen, y2), bracket_color, bthick)
    cv2.line(img, (x1, y2), (x1, y2 - clen), bracket_color, bthick)
    cv2.line(img, (x2, y2), (x2 - clen, y2), bracket_color, bthick)
    cv2.line(img, (x2, y2), (x2 - clen, y2), bracket_color, bthick)

    if label:
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.40, 1)
        badge_y1 = max(38, y1 - 20)
        badge_y2 = max(38 + th + 4, y1 - 2)
        bg_col = (110, 15, 20) if is_critical else (15, 23, 42)
        border_col = (0, 0, 255) if is_critical else (70, 85, 105)
        cv2.rectangle(img, (x1, badge_y1), (x1 + tw + 8, badge_y2), bg_col, -1)
        cv2.rectangle(img, (x1, badge_y1), (x1 + tw + 8, badge_y2), border_col, 1)
        cv2.putText(img, label, (x1 + 4, badge_y2 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA)


def draw_forensic_hud(frame, phase: str, t: float, summary: dict, ev_boxes=None, inc_type=""):
    img = frame.copy()
    h, w = img.shape[:2]

    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (w, 36), (15, 23, 42), -1)
    cv2.rectangle(overlay, (0, h - 24), (w, h), (15, 23, 42), -1)
    cv2.addWeighted(overlay, 0.88, img, 0.12, 0, img)

    phase_cfg = {
        "event": ("CRITICAL EVENT TRIGGER", (30, 30, 220)),
        "post": ("AFTERMATH MONITORING", (12, 88, 234)),
        "pre": ("BASELINE MONITORING", (34, 139, 34)),
    }
    badge_label, badge_color = phase_cfg.get(phase, ("SURVEILLANCE FRAME", (70, 70, 70)))

    (bw, _), _ = cv2.getTextSize(badge_label, cv2.FONT_HERSHEY_SIMPLEX, 0.44, 1)
    cv2.rectangle(img, (8, 6), (16 + bw, 28), badge_color, -1)
    cv2.putText(img, badge_label, (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (255, 255, 255), 1, cv2.LINE_AA)

    time_str = f"VIDEO TS: {fmt_ts(t)} (T={t:.1f}s)"
    cv2.putText(img, time_str, (24 + bw, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (240, 240, 240), 1, cv2.LINE_AA)

    vehs = summary.get("vehicles") or 0
    pers = summary.get("persons") or 0
    conf_val = summary.get("conf")
    conf_str = f" | CONF: {int(conf_val * 100)}%" if conf_val is not None else ""
    stat_str = f"TARGETS: {vehs} VEH, {pers} PER{conf_str}"
    (sw, _), _ = cv2.getTextSize(stat_str, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
    cv2.putText(img, stat_str, (max(w - sw - 12, 28 + bw + 150), 22), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 225, 255), 1, cv2.LINE_AA)

    if ev_boxes:
        for box, lbl in ev_boxes:
            draw_tactical_box(img, box, (40, 40, 240), f"[CRITICAL TRIGGER] {lbl.upper()}", is_critical=True)

    objs = summary.get("objects", [])
    for o in objs:
        bx = o.get("box")
        if not bx or len(bx) != 4:
            continue
        is_in_ev = False
        if ev_boxes:
            for eb, _ in ev_boxes:
                if iou(bx, eb) > 0.35:
                    is_in_ev = True
                    break
        if is_in_ev:
            continue
        color = (60, 200, 240) if o.get("cls") == 0 else (240, 160, 50)
        name = o.get("name", "obj").upper()
        oid = o.get("id", "?")
        spd = o.get("speed_label", "")
        posture = o.get("posture", "")
        if o.get("cls") == 0 and posture:
            lbl_text = f"#{oid} PER · {posture.split()[0].upper()}"
        else:
            lbl_text = f"#{oid} {name}" + (f" · {spd.upper()}" if spd else "")
        draw_tactical_box(img, bx, color, lbl_text, is_critical=False)

    bottom_txt_left = "INCIDENT DESK FORENSIC CCTV ENGINE · YOLOv8n + KINEMATIC TELEMETRY"
    cv2.putText(img, bottom_txt_left, (12, h - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 200, 220), 1, cv2.LINE_AA)
    bottom_txt_right = f"RES: {w}x{h} | EVIDENCE RECORD"
    (rw, _), _ = cv2.getTextSize(bottom_txt_right, cv2.FONT_HERSHEY_SIMPLEX, 0.36, 1)
    if w - rw - 12 > 420:
        cv2.putText(img, bottom_txt_right, (w - rw - 12, h - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (140, 160, 180), 1, cv2.LINE_AA)
    return img


class VideoAnalyzer:
    """Samples frames, keeps a rolling buffer, and collects before/during/after evidence per event."""

    def __init__(self, path, zone=None):
        self.path = str(path)
        self.engine = RuleEngine(zone)
        self.motion = MotionMonitor()
        self.last: dict[str, float] = {}
        self.use_yolo = False
        self.buffer: deque = deque()   # rolling buffer of JPEG-compressed frames
        self.pending: list[dict] = []  # events still collecting post-event frames
        self.completed: list[dict] = []

    @staticmethod
    def _jpeg(img, q=82) -> bytes:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
        return buf.tobytes() if ok else b""

    def _annotated_frame(self, frame, phase, t, summary, ev_boxes=None, inc_type="") -> bytes:
        annotated = draw_forensic_hud(frame, phase, t, summary, ev_boxes, inc_type)
        return self._jpeg(annotated, 84)

    def _annotated(self, frame, ev, t) -> bytes:
        return self._annotated_frame(frame, "event", t, self.engine.summary, ev.get("boxes"), ev.get("type"))

    def _pick_pre(self, t):
        chosen = []
        cands = [b for b in self.buffer if b["t"] <= t - 0.3]
        for k in range(EVIDENCE_PRE_SEC, 0, -1):
            if not cands:
                break
            best = min(cands, key=lambda b: abs(b["t"] - (t - k)))
            if all(best is not c for c in chosen):
                chosen.append(best)
        return chosen

    def _process(self, frame, t):
        h, w = frame.shape[:2]
        if w > 960:
            frame = cv2.resize(frame, (960, int(h * 960 / w)))
        events = []
        dets = Detector.detect(frame) if self.use_yolo else None
        if dets is not None:
            events += self.engine.step(dets, t, frame.shape[:2])
            summary = self.engine.summary
        else:
            summary = dict(vehicles=None, persons=None, conf=None)
        m = self.motion.update(frame, t)
        if m:
            events.append(m)
        rec = dict(t=t, jpeg=self._annotated_frame(frame, "pre", t, summary), summary=summary)

        for p in list(self.pending):  # post-event evidence, one frame per second
            if t - p["last_t"] >= 1.0 and len(p["post"]) < EVIDENCE_POST_SEC:
                post_jpeg = self._annotated_frame(frame, "post", t, summary, p.get("boxes"), p.get("type"))
                p["post"].append(dict(t=t, jpeg=post_jpeg, summary=summary))
                p["last_t"] = t
            if len(p["post"]) >= EVIDENCE_POST_SEC:
                self.completed.append(dict(key=p["key"], frames=p["post"]))
                self.pending.remove(p)

        out = []
        for ev in events:
            if t - self.last.get(ev["type"], -1e9) < EVENT_COOLDOWN_SEC:
                continue
            self.last[ev["type"]] = t
            ev["key"] = uuid.uuid4().hex
            ev["jpeg"] = self._annotated_frame(frame, "event", t, summary, ev.get("boxes"), ev.get("type"))
            ev["frames"] = dict(pre=self._pick_pre(t), event=dict(t=t, jpeg=ev["jpeg"], summary=summary))
            self.pending.append(dict(key=ev["key"], last_t=t, post=[], boxes=ev.get("boxes", []), type=ev.get("type", "")))
            out.append(ev)

        self.buffer.append(rec)
        while self.buffer and t - self.buffer[0]["t"] > EVIDENCE_PRE_SEC + 0.5:
            self.buffer.popleft()
        return out


    def _take_post(self):
        done, self.completed = self.completed, []
        return done

    def segments(self):
        """Yield one dict per SEGMENT_SEC of video. Blocking; run it in a worker thread."""
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            raise RuntimeError("Could not open video file")
        try:
            self.use_yolo = Detector.model() is not None
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            duration = total / fps if total > 0 else 0.0
            step = max(1, round(fps / SAMPLE_FPS))
            idx, seg_start, seg_end, events = 0, 0.0, SEGMENT_SEC, []
            t = 0.0
            while cap.grab():
                t = idx / fps
                if idx % step == 0:
                    ok, frame = cap.retrieve()
                    if ok:
                        events += self._process(frame, t)
                idx += 1
                if t >= seg_end:
                    yield dict(t_start=seg_start, t_end=t, events=events, post=self._take_post(),
                               progress=min(0.99, t / duration) if duration else 0.0, duration=duration,
                               summary=dict(self.engine.summary) if hasattr(self.engine, 'summary') else {})
                    seg_start, seg_end, events = t, seg_end + SEGMENT_SEC, []
            for p in self.pending:  # video ended: close out whatever post-event frames exist
                self.completed.append(dict(key=p["key"], frames=p["post"]))
            self.pending.clear()
            yield dict(t_start=seg_start, t_end=t, events=events, post=self._take_post(),
                       progress=1.0, duration=duration or t,
                       summary=dict(self.engine.summary) if hasattr(self.engine, 'summary') else {})
        finally:
            cap.release()
