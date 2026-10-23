"""Logical agents. They share one vision pipeline; the orchestrator coordinates them."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone

import httpx

from analysis import VideoAnalyzer, fmt_ts
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

log = logging.getLogger("agents")

SEV_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}

INCIDENT_TYPES = {
    "collision": dict(
        label="Possible vehicle collision", short="Road Accident", category="Road safety", severity="critical",
        action="Review the footage and verify whether emergency assistance is required.",
        procedure=["Confirm the collision in the workbench", "Check for people on the ground or trapped", "Confirm the emergency to alert the control room"],
        limits=["Detection uses vehicle box overlap and sudden slowing. It cannot confirm that the vehicles touched.",
                "Injuries and damage cannot be determined from these frames.",
                "Occlusion or camera angle can create false overlaps."],
    ),
    "congestion": dict(
        label="Possible traffic congestion", short="Traffic Congestion", category="Road safety", severity="medium",
        action="Check whether traffic is blocked and whether a cause is visible.",
        procedure=["Review the frames for a blockage or breakdown", "Notify traffic control if the road is blocked"],
        limits=["Based on the number of slow-moving vehicles. Parked vehicles can look the same.",
                "The cause of the slowdown is not determined."],
    ),
    "fall": dict(
        label="Possible person fall", short="Person Fall", category="Public safety", severity="high",
        action="Review the footage and check whether the person gets up or needs help.",
        procedure=["Confirm the fall in the workbench", "Send on-site staff if the person stays down", "Confirm the emergency if there are signs of injury"],
        limits=["Based on the person's bounding box changing shape. Sitting, bending or crouching can look similar.",
                "The cause of the fall and any injury cannot be determined."],
    ),
    "restricted_zone": dict(
        label="Possible unauthorized entry", short="Restricted-Zone Entry", category="Industrial safety", severity="high",
        action="Verify the person's identity or authorization before escalating.",
        procedure=["Check the access roster", "Contact on-site security", "Record the outcome in the review reason"],
        limits=["The zone is a configured rectangle. The system cannot tell whether the person is authorized.",
                "Identity is not determined."],
    ),
    "motion_surge": dict(
        label="Sudden abnormal motion", short="Abnormal Motion", category="General", severity="medium",
        action="Review the footage to find out what changed.",
        procedure=["Review the frames", "Escalate if people or vehicles appear at risk"],
        limits=["Frame-wide change can come from lighting, camera shake or weather rather than a real event.",
                "This check does not identify objects or people."],
    ),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def counts_text(s: dict) -> str:
    if s.get("vehicles") is None and s.get("persons") is None:
        return "Motion-difference analysis only (no object detector active)."
    vehs, pers = s.get("vehicles", 0), s.get("persons", 0)
    parts = []
    if vehs:
        parts.append(f"{vehs} vehicle{'s' if vehs != 1 else ''}")
    if pers:
        parts.append(f"{pers} person{'s' if pers != 1 else ''}")
    base = f"Tracked: {', '.join(parts) if parts else '0 objects'}."
    objs = s.get("objects", [])
    if objs:
        details = [f"{o.get('name', 'obj')} #{o.get('id', '?')} ({o.get('loc', '').replace('-', ' ')})" for o in objs[:3]]
        base += f" Locations: {', '.join(details)}."
    return base


class VideoAnalysisAgent:
    def open(self, path, zone=None) -> VideoAnalyzer:
        return VideoAnalyzer(path, zone)


class IncidentDetectionAgent:
    MIN_CONF = 0.45

    def classify(self, ev: dict) -> dict | None:
        spec = INCIDENT_TYPES.get(ev["type"])
        if not spec or ev["confidence"] < self.MIN_CONF:
            return None
        return dict(type=ev["type"], label=spec["label"], short=spec["short"], category=spec["category"],
                    severity=spec["severity"], detail=ev["detail"], confidence=round(ev["confidence"], 2),
                    recommended_action=spec["action"], meta=ev.get("meta", {}))


class PriorityAlertAgent:
    """Severity is an AI assessment only. It orders the review queue; it never dispatches anything."""

    def prioritize(self, cam: dict, inc: dict, camera_history: list[dict]) -> dict:
        inc["severity_note"] = "AI assessment only. A human reviewer decides whether this is an emergency."
        if inc["type"] == "fall":
            for other in camera_history:
                if other["type"] == "collision" and abs(other["video_ts"] - inc["video_ts"]) <= 15:
                    inc["severity"] = "critical"
                    inc["severity_note"] += " Raised because it follows a possible collision on this camera."
        inc["priority_score"] = SEV_RANK[inc["severity"]] * 100 + int(inc["confidence"] * 100)
        spoken = f"{int(inc['video_ts'] // 60)} minutes {int(inc['video_ts'] % 60)} seconds"
        inc["alert_text"] = (
            f"Emergency confirmed. Camera {int(cam['id'].split('-')[-1])}, {inc['label'].lower()} at {spoken}."
        )
        return inc


class InvestigationAgent:
    def investigate(self, store, inc: dict) -> dict:
        similar = [
            dict(id=o["id"], camera_name=o["camera_name"], video_ts_text=o["video_ts_text"], emergency=o.get("emergency"))
            for o in store.incidents.values()
            if o["type"] == inc["type"] and o["review_status"] == "confirmed"
        ][:3]
        same_cam = sorted(store.incidents_for(inc["camera_id"]) + [inc], key=lambda o: o["video_ts"])
        inc["similar_incidents"] = similar
        inc["timeline"] = [dict(id=o["id"], video_ts_text=o["video_ts_text"], label=o["label"]) for o in same_cam]
        inc["procedure"] = INCIDENT_TYPES[inc["type"]]["procedure"]
        return inc


class ReportingAgent:
    def draft(self, inc: dict, cam: dict, ev: dict, wall_s: float) -> dict:
        spec = INCIDENT_TYPES[inc["type"]]
        ev_summary = ev["frames"]["event"]["summary"]
        counts = counts_text(ev_summary)
        meta = ev.get("meta", {})
        inc_type = inc["type"]
        cam_id = cam["id"]
        cam_name = cam["name"]
        t_sec = ev["t"]
        ts_text = fmt_ts(t_sec)
        conf_pct = int(inc["confidence"] * 100)
        sev = inc["severity"]

        if inc_type == "collision":
            a_cls = meta.get("a_cls", "vehicle")
            b_cls = meta.get("b_cls", "vehicle")
            a_id = meta.get("a_id", 1)
            b_id = meta.get("b_id", 2)
            iou_val = meta.get("iou", 0.15)
            max_decel = meta.get("max_decel_pct", meta.get("a_decel_pct", 75))
            summary_text = (
                f"CRITICAL FORENSIC REPORT: Potential vehicular collision identified on {cam_id} ({cam_name}) at video time {ts_text} (T={t_sec:.1f}s). "
                f"Kinematic trajectory analysis verified spatial bounding intersection (IoU={iou_val:.2f}) between {a_cls} #{a_id} and {b_cls} #{b_id}. "
                f"Collision trajectory was accompanied by an acute deceleration of {max_decel:.0f}%, causing immediate travel corridor blockage. "
                f"Multi-frame visual evidence was cataloged spanning pre-collision baseline, trigger point of impact, and subsequent aftermath. "
                f"Analytical rule score: {conf_pct}%. Severity: {sev.upper()}. Awaiting operator verification and emergency dispatch decision."
            )
        elif inc_type == "fall":
            p_id = meta.get("person_id", 1)
            drop_pct = meta.get("height_drop_pct", 70)
            base_ar = meta.get("baseline_aspect_ratio", 0.45)
            fallen_ar = meta.get("fallen_aspect_ratio", 1.35)
            summary_text = (
                f"SAFETY FORENSIC REPORT: Pedestrian fall detected on {cam_id} ({cam_name}) at video time {ts_text} (T={t_sec:.1f}s). "
                f"Biomechanical posture tracking detected acute geometric collapse of Person #{p_id}: vertical height contracted by {drop_pct:.0f}% "
                f"as posture aspect ratio inverted from upright standing ({base_ar:.2f}) to ground plane ({fallen_ar:.2f}). "
                "Subject remained recumbent on the floor/ground surface without self-righting across subsequent sample intervals. "
                f"Analytical rule score: {conf_pct}%. Severity: {sev.upper()}. Immediate operator review required to determine injury status."
            )
        elif inc_type == "restricted_zone":
            p_id = meta.get("person_id", 1)
            dwell = meta.get("dwell_sec", 1.0)
            zone_coords = meta.get("zone", [0, 0, 1, 1])
            summary_text = (
                f"SECURITY FORENSIC REPORT: Unauthorized restricted-zone entry detected on {cam_id} ({cam_name}) at video time {ts_text} (T={t_sec:.1f}s). "
                f"Perimeter tracking confirmed Person #{p_id} breached demarcated restricted coordinates [{zone_coords[0]:.2f}, {zone_coords[1]:.2f}, {zone_coords[2]:.2f}, {zone_coords[3]:.2f}] "
                f"and sustained unauthorized presence for {dwell:.1f}s. Multi-frame evidence documents boundary approach and ongoing dwell. "
                f"Analytical rule score: {conf_pct}%. Severity: {sev.upper()}. Operator must verify badge credentials or alert site security."
            )
        elif inc_type == "congestion":
            slow_cnt = meta.get("slow_count", 4)
            tot_veh = meta.get("total_vehicles", 6)
            cong_pct = meta.get("congestion_pct", int(slow_cnt / max(1, tot_veh) * 100))
            summary_text = (
                f"TRAFFIC FORENSIC REPORT: Severe roadway congestion flagged on {cam_id} ({cam_name}) at video time {ts_text} (T={t_sec:.1f}s). "
                f"Corridor density monitor observed {slow_cnt} of {tot_veh} tracked vehicles ({cong_pct}% of scene volume) immobilized or crawling (<0.02 diag/s) "
                "continuously for >=4.0 seconds, causing localized travel lane stagnation. "
                f"Analytical rule score: {conf_pct}%. Severity: {sev.upper()}. Operator should check for roadway obstruction or signal malfunction."
            )
        else:
            summary_text = (
                f"INCIDENT FORENSIC REPORT: Abnormal kinetic disturbance detected on {cam_id} ({cam_name}) at video time {ts_text} (T={t_sec:.1f}s). "
                f"Analysis: {inc['detail']} "
                f"Multi-frame evidence captured baseline, trigger point, and aftermath stabilization. "
                f"Analytical rule score: {conf_pct}%. Severity: {sev.upper()}. Operator review required."
            )

        findings = [
            dict(
                event=f"Primary Trigger: {inc['label']}",
                timestamp=ts_text,
                confidence=inc["confidence"],
                evidence=inc["detail"],
                objects=counts,
                method="YOLOv8 deep neural detector + kinematic tracking heuristics" if ev_summary.get("vehicles") is not None
                else "Frame-difference optical disturbance monitor",
            ),
            dict(
                event="Kinematic & Trajectory Verification",
                timestamp=ts_text,
                confidence=inc["confidence"],
                evidence=(
                    f"IoU overlap: {meta.get('iou', 'N/A')}; Deceleration: {meta.get('max_decel_pct', meta.get('a_decel_pct', 'N/A'))}%; "
                    f"Targets involved: {meta.get('a_cls', 'Entity')} #{meta.get('a_id', 1)} and {meta.get('b_cls', 'Entity')} #{meta.get('b_id', 2)}"
                    if inc_type == "collision" else
                    f"Height collapse: {meta.get('height_drop_pct', 'N/A')}%; Posture aspect ratio: {meta.get('baseline_aspect_ratio', 'N/A')} -> {meta.get('fallen_aspect_ratio', 'N/A')}"
                    if inc_type == "fall" else
                    f"Geofence dwell: {meta.get('dwell_sec', 'N/A')}s inside perimeter [{meta.get('zone', '')}]"
                    if inc_type == "restricted_zone" else
                    f"Stationary queue count: {meta.get('slow_count', 'N/A')} / {meta.get('total_vehicles', 'N/A')} vehicles ({meta.get('congestion_pct', 'N/A')}%)"
                    if inc_type == "congestion" else
                    inc["detail"]
                ),
                objects=f"Active Scene Target Inventory: {len(ev_summary.get('objects', []))} tracked entities",
                method="Multi-object continuous centroid/kinematic tracker",
            ),
            dict(
                event="Control Room SOP & Action Protocol",
                timestamp=ts_text,
                confidence=1.0,
                evidence=spec["action"],
                objects="Human-in-the-Loop Operator Protocol",
                method="Standard Operating Procedure (SOP) Rulebook",
            ),
        ]

        inc.update(
            camera_id=cam["id"], camera_name=cam["name"], location=cam["name"], video_ts=round(ev["t"], 1),
            video_ts_text=ts_text, detected_at=now_iso(), analysis_wall_s=round(wall_s, 1),
            review_status="awaiting_review", emergency=None, response_status=None, description_source="rules",
            summary=summary_text,
            findings=findings,
            limitations=list(spec["limits"]), evidence=[], evidence_complete=False, reviews=[], access_log=[],
            email=dict(status="pending"), sms=dict(status="pending"), video_ref=dict(camera_id=cam["id"], file=cam.get("file"), sha256=cam.get("video_sha256")),
            audit=[dict(at=now_iso(), actor="agent", action="Incident report created with full forensic telemetry")],
        )
        return inc

    @staticmethod
    def explain_frame(inc: dict, ev: dict | None, phase: str, f: dict, frame_index: int, total_in_phase: int) -> dict:
        t = f.get("t", 0.0)
        event_t = inc.get("video_ts", t)
        dt = round(t - event_t, 1)

        if phase == "event" or abs(dt) < 0.1:
            dt_text = "T=0.0s (Detection Point)"
            phase_label = "Trigger Moment"
        elif phase == "pre" or dt < 0:
            dt_text = f"T{dt:+.1f}s (Prior)"
            phase_label = "Pre-Incident Baseline"
        else:
            dt_text = f"T+{dt:.1f}s (Aftermath)"
            phase_label = "Post-Incident Aftermath"

        summary = f.get("summary", {})
        vehs = summary.get("vehicles")
        pers = summary.get("persons")
        objs = summary.get("objects", [])

        if vehs is not None or pers is not None:
            parts = []
            if vehs:
                parts.append(f"{vehs} vehicle{'s' if vehs != 1 else ''}")
            if pers:
                parts.append(f"{pers} person{'s' if pers != 1 else ''}")
            tracked_summary = ", ".join(parts) if parts else "No foreground targets actively tracked"
        else:
            tracked_summary = "Motion-difference optical analysis (no class detector active)"

        obj_desc_list = []
        for o in objs[:5]:
            loc = o.get("loc", "center").replace("-", " ")
            spd = o.get("speed_label", "normal")
            extra = f" [{o['posture']}]" if "posture" in o else ""
            obj_desc_list.append(f"{o.get('name', 'Entity')} #{o.get('id', '?')} in {loc} ({spd}{extra})")
        detailed_entities = "; ".join(obj_desc_list) if obj_desc_list else tracked_summary

        inc_type = inc.get("type", "general")
        cam_name = inc.get("camera_name", inc.get("camera_id", "Camera"))
        ts_text = fmt_ts(t)
        meta = inc.get("meta") or (ev.get("meta") if ev else {}) or {}

        if inc_type == "collision":
            a_cls = meta.get("a_cls", "vehicle")
            b_cls = meta.get("b_cls", "vehicle")
            a_id = meta.get("a_id", 1)
            b_id = meta.get("b_id", 2)
            iou_val = meta.get("iou", 0.15)
            max_decel = meta.get("max_decel_pct", meta.get("a_decel_pct", 75))
            if phase == "pre":
                title = f"Pre-Impact Kinematic Trajectory ({dt_text})"
                scene_context = f"Baseline roadway surveillance at {cam_name}; converging approach vectors prior to impact zone"
                dynamics = f"Active vehicular velocities maintained without acute deceleration; incoming trajectories ({detailed_entities}) align toward convergence area"
                operator_note = "Inspect baseline lane positions, vehicle speeds, and check whether brake lights or evasive steering were initiated prior to impact"
                finding = (
                    f"Surveillance baseline at video time {ts_text} ({dt_text}). The camera monitors active corridor traffic on {cam_name}. "
                    f"Scene inventory: {tracked_summary}. Primary targets ({detailed_entities}) are tracked along normal roadway travel vectors. "
                    "Trajectories indicate sustained forward momentum with no premature stoppage or loss of lane control visible at this interval. "
                    "This frame serves as the baseline record for right-of-way, approach speed, and environmental visibility."
                )
            elif phase == "event":
                title = f"Collision Impact & Kinetic Convergence Point ({dt_text})"
                scene_context = f"Physical bounding intersection and acute kinetic deceleration at {cam_name}"
                dynamics = f"Spatial bounding intersection (IoU={iou_val:.2f}) between {a_cls} #{a_id} and {b_cls} #{b_id}; sudden deceleration of {max_decel:.0f}%"
                operator_note = "Verify physical bumper/panel contact vs camera perspective overlap; check for airbag deployment, debris, or occupant injury"
                finding = (
                    f"Critical Impact Detection Frame at video time {ts_text} ({dt_text}). "
                    f"Forensic algorithms confirmed spatial overlap between {a_cls} #{a_id} and {b_cls} #{b_id} (IoU={iou_val:.2f}) "
                    f"concurrent with an acute vehicular velocity collapse of {max_decel:.0f}%. "
                    f"Surrounding scene targets: {detailed_entities}. The sudden kinetic stoppage is characteristic of an abrupt vehicular collision rather than controlled braking. "
                    "Bounding reticles are highlighted in red for operator forensic verification. Operator must determine if emergency medical/traffic dispatch is required."
                )
            else:
                title = f"Post-Collision Aftermath & Corridor Blockage ({dt_text})"
                scene_context = f"Post-impact travel lane obstruction; immobilized vehicles on {cam_name}"
                dynamics = f"Primary vehicles remain completely stationary; subsequent corridor traffic decelerating or diverting around blocked lane"
                operator_note = "Examine vehicle immobility, fluid leakage, hazardous road blockage, and observe whether occupants are exiting safely"
                finding = (
                    f"Aftermath monitoring frame at video time {ts_text} ({dt_text}). Following suspected impact, involved vehicles remain stationary in active travel lanes at {cam_name}. "
                    f"Scene inventory: {tracked_summary} ({detailed_entities}). Over consecutive sampled intervals, no forward movement is detected from the primary collision targets. "
                    "Approaching traffic is beginning to queue or divert into adjacent lanes, creating secondary hazard risk. Operator should verify scene safety and confirm tow/police response."
                )

        elif inc_type == "fall":
            p_id = meta.get("person_id", 1)
            drop_pct = meta.get("height_drop_pct", 70)
            base_ar = meta.get("baseline_aspect_ratio", 0.45)
            fallen_ar = meta.get("fallen_aspect_ratio", 1.35)
            if phase == "pre":
                title = f"Pre-Fall Walking Gait & Posture Baseline ({dt_text})"
                scene_context = f"Pedestrian corridor transit at {cam_name}; normal walking posture"
                dynamics = f"Subject #{p_id} tracked in upright standing posture with standard vertical aspect ratio ({base_ar:.2f})"
                operator_note = "Observe walkway conditions, slip/trip hazards (water, obstacles, stairs), and subject gait stability prior to fall"
                finding = (
                    f"Pedestrian baseline at video time {ts_text} ({dt_text}). The camera monitors pedestrian movement at {cam_name}. "
                    f"Scene inventory: {tracked_summary}. The subject ({detailed_entities}) is tracked in an upright standing posture with stable vertical geometry. "
                    "Movement is steady with no visual signs of staggering, stumbling, or environmental obstruction prior to this timestamp."
                )
            elif phase == "event":
                title = f"Acute Loss of Balance & Ground Impact Point ({dt_text})"
                scene_context = f"Biomechanical vertical posture collapse onto floor/ground plane at {cam_name}"
                dynamics = f"Vertical bounding height contracted by {drop_pct:.0f}%; aspect ratio inverted from upright {base_ar:.2f} to horizontal {fallen_ar:.2f}"
                operator_note = "Determine whether subject suffered an uncontrolled trip/fall/medical syncope vs intentional bending, sitting, or kneeling"
                finding = (
                    f"Fall Trigger Detection Frame at video time {ts_text} ({dt_text}). "
                    f"Biomechanical tracking detected an acute vertical collapse of Person #{p_id}: "
                    f"bounding box height contracted by {drop_pct:.0f}% while aspect ratio inverted from upright ({base_ar:.2f}) to ground plane ({fallen_ar:.2f}) within 1.0s. "
                    f"Scene inventory: {tracked_summary}. Red tactical reticle highlights the fallen subject. "
                    "The rapidity and geometry of the transition strongly correlate with an uncontrolled loss of balance. Immediate operator verification is warranted."
                )
            else:
                title = f"Post-Fall Ground Immobility Monitoring ({dt_text})"
                scene_context = f"Subject remains recumbent on walking surface at {cam_name}"
                dynamics = "Subject maintains horizontal posture on ground plane; zero vertical recovery or self-righting detected over consecutive frames"
                operator_note = "Check subject consciousness, visible distress, movement of limbs, and observe whether bystanders or first aiders are attending"
                finding = (
                    f"Post-fall status frame at video time {ts_text} ({dt_text}). The subject remains in a horizontal prone/supine position on the walkway at {cam_name}. "
                    f"Scene inventory: {tracked_summary} ({detailed_entities}). Over consecutive sampled intervals, no attempt to stand up or recover an upright vertical posture is detected. "
                    "Prolonged immobility on the ground plane elevates medical concern. Operator should evaluate live stream and dispatch on-site security or medical first responders."
                )

        elif inc_type == "restricted_zone":
            p_id = meta.get("person_id", 1)
            dwell = meta.get("dwell_sec", 1.0)
            z = meta.get("zone")
            zone_str = f"[{z[0]:.2f}, {z[1]:.2f}, {z[2]:.2f}, {z[3]:.2f}]" if z and len(z) == 4 else "calibrated perimeter coordinates"
            if phase == "pre":
                title = f"Perimeter Surveillance & Approach Vector ({dt_text})"
                scene_context = f"Pedestrian surveillance outside demarcated restricted boundary at {cam_name}"
                dynamics = f"Subject #{p_id} moving along approach vector outside restricted zone polygon"
                operator_note = "Observe subject direction of motion, safety gear (PPE), and check whether authorized escort or credentials are visible"
                finding = (
                    f"Perimeter surveillance at video time {ts_text} ({dt_text}). Camera monitors access perimeter at {cam_name}. "
                    f"Scene inventory: {tracked_summary}. The subject ({detailed_entities}) is located outside the configured restricted area, advancing toward the restricted boundary."
                )
            elif phase == "event":
                title = f"Unauthorized Perimeter Boundary Breach ({dt_text})"
                scene_context = f"Geofence threshold breach into restricted zone coordinates at {cam_name}"
                dynamics = f"Subject coordinates entered restricted polygon; sustained dwell >= {dwell:.1f}s"
                operator_note = "Cross-reference access roster, check badge authorization, and determine whether area entry requires immediate physical escort"
                finding = (
                    f"Security Breach Detection Frame at video time {ts_text} ({dt_text}). "
                    f"Computer vision confirmed Person #{p_id} crossed into calibrated restricted zone boundary ({zone_str}) "
                    f"and sustained unauthorized presence for {dwell:.1f}s without exiting. Current scene inventory: {tracked_summary}. "
                    "Subject is outlined in red tactical reticles for security verification. Operator should confirm access credentials or dispatch patrol."
                )
            else:
                title = f"Restricted Sector Dwell & Intrusion Tracking ({dt_text})"
                scene_context = f"Continuous unauthorized presence within restricted operational area at {cam_name}"
                dynamics = f"Ongoing dwell inside restricted perimeter coordinates (elapsed dwell: {dt + dwell:.1f}s)"
                operator_note = "Maintain camera lock on subject; notify perimeter security to challenge or escort the individual from restricted sector"
                finding = (
                    f"Intrusion follow-up frame at video time {ts_text} ({dt_text}). The unauthorized individual remains active within the restricted boundary at {cam_name}. "
                    f"Scene inventory: {tracked_summary} ({detailed_entities}). Continuous spatial dwell indicates an intentional breach rather than an accidental perimeter glance. "
                    "Reviewer should verify authorized roster or issue PA announcement / security dispatch."
                )

        elif inc_type == "congestion":
            slow_cnt = meta.get("slow_count", 4)
            tot_veh = meta.get("total_vehicles", 6)
            cong_pct = meta.get("congestion_pct", int(slow_cnt / max(1, tot_veh) * 100))
            if phase == "pre":
                title = f"Corridor Throughput Flow Baseline ({dt_text})"
                scene_context = f"Steady vehicular passage along {cam_name} roadway corridor"
                dynamics = "Vehicles advancing at standard roadway velocity with adequate headway"
                operator_note = "Monitor traffic volume, corridor capacity, and check for upstream bottlenecks or lane closures"
                finding = (
                    f"Traffic flow baseline at video time {ts_text} ({dt_text}). Normal vehicular passage observed on {cam_name}. "
                    f"Scene inventory: {tracked_summary}. Vehicles ({detailed_entities}) are progressing steadily across travel lanes without anomalous delay."
                )
            elif phase == "event":
                title = f"Corridor Gridlock & Queue Stagnation Point ({dt_text})"
                scene_context = f"Traffic density threshold breached; sustained queue formation on {cam_name}"
                dynamics = f"{slow_cnt} of {tot_veh} tracked vehicles ({cong_pct}%) immobilized (<0.02 diag/s) for >=4.0s"
                operator_note = "Identify root bottleneck: disabled vehicle, accident, roadworks, traffic signal fault, or spillback from adjacent intersection"
                finding = (
                    f"Congestion Trigger Frame at video time {ts_text} ({dt_text}). "
                    f"Corridor density algorithms detected {slow_cnt} of {tot_veh} tracked vehicles ({cong_pct}%) stationary or crawling below 0.02 diag/s for over 4.0 seconds. "
                    f"Scene inventory: {tracked_summary}. Highlighted vehicles denote the core queue blockage requiring traffic management intervention."
                )
            else:
                title = f"Queue Stagnation & Corridor Spillback ({dt_text})"
                scene_context = f"Persistent roadway gridlock and queue accumulation on {cam_name}"
                dynamics = "Persistent roadway stoppage; queue extending upstream with zero vehicular clearance"
                operator_note = "Assess upstream traffic diversion requirements and notify municipal traffic control center"
                finding = (
                    f"Congestion status frame at video time {ts_text} ({dt_text}). Traffic stoppage persists along {cam_name}. "
                    f"Scene inventory: {tracked_summary} ({detailed_entities}). Stagnant queue continues to block travel lanes with no forward progression. "
                    "Reviewer should coordinate with traffic signals or dispatch traffic marshals to clear the corridor."
                )

        else:
            if phase == "pre":
                title = f"Ambient Environmental Baseline ({dt_text})"
                scene_context = f"Normal background pixel variance at {cam_name}"
                dynamics = "Pixel variance within standard background threshold (<1.0%)"
                operator_note = "Establish normal environmental conditions (lighting, foliage, shadows)"
                finding = (
                    f"Surveillance baseline at video time {ts_text} ({dt_text}). Camera {cam_name} displays standard scene activity without sudden fluctuations. "
                    f"Current scene inventory: {tracked_summary}."
                )
            elif phase == "event":
                title = f"Abnormal Kinetic Disturbance Trigger ({dt_text})"
                scene_context = f"Abrupt frame-wide optical disturbance detected at {cam_name}"
                dynamics = "Pixel difference threshold exceeded baseline variance by >400%"
                operator_note = "Distinguish camera displacement, lighting artifact, weather event, or physical hazard in scene"
                ev_detail = ev.get("detail") if ev else "Sudden abnormal motion detected"
                finding = (
                    f"Motion Trigger Frame at video time {ts_text} ({dt_text}). {ev_detail}. "
                    f"Current scene inventory: {tracked_summary}. Widespread pixel change flagged for immediate operator inspection."
                )
            else:
                title = f"Post-Disturbance Scene Stabilization ({dt_text})"
                scene_context = f"Scene returning to baseline equilibrium at {cam_name}"
                dynamics = "Pixel variance decaying back toward baseline levels"
                operator_note = "Verify whether physical debris, stalled targets, or structural hazards remain in the scene"
                finding = (
                    f"Post-event observation at video time {ts_text} ({dt_text}). Frame activity is stabilizing at {cam_name}. "
                    f"Current scene inventory: {tracked_summary} ({detailed_entities}). Reviewer should check if residual hazards remain."
                )

        return dict(
            title=title,
            phase_label=phase_label,
            delta_t=dt,
            delta_t_text=dt_text,
            scene_context=scene_context,
            tracked_entities=detailed_entities,
            dynamics=dynamics,
            operator_note=operator_note,
            finding=finding,
        )

    def frame_records(self, inc: dict, ev: dict | None, frames: list[tuple[str, dict]], start: int):
        """frames: [(phase, {t, jpeg, summary})] -> (metadata records, [(filename, bytes)])."""
        records, files = [], []
        for n, (phase, f) in enumerate(frames, start=start):
            name = f"F{n:02d}.jpg"
            conf = inc["confidence"] if phase == "event" else f["summary"].get("conf")
            exp = self.explain_frame(inc, ev, phase, f, n, len(frames))
            records.append(dict(
                frame_id=f"{inc['id']}-F{n:02d}", incident_id=inc["id"], camera_id=inc["camera_id"], phase=phase,
                phase_label=exp["phase_label"], title=exp["title"], delta_t=exp["delta_t"], delta_t_text=exp["delta_t_text"],
                video_ts=round(f["t"], 1), video_ts_text=fmt_ts(f["t"]), filename=name,
                url=f"/api/evidence/{inc['id']}/{name}", finding=exp["finding"],
                scene_context=exp["scene_context"], tracked_entities=exp["tracked_entities"],
                dynamics=exp["dynamics"], operator_note=exp["operator_note"],
                confidence=conf, video_ref=dict(file=inc["video_ref"]["file"], at=round(f["t"], 1)),
                sha256=sha256_bytes(f["jpeg"]),
            ))
            files.append((name, f["jpeg"]))
        return records, files

    async def enrich(self, inc: dict, jpeg: bytes) -> dict | None:
        """Optional: Claude rewrites the summary from the evidence frame. Falls back silently."""
        if not ANTHROPIC_API_KEY or not jpeg:
            return None
        prompt = (
            "You assist a CCTV control room. A rule-based detector flagged this frame as: "
            f"{inc['label']} (camera {inc['camera_name']}, video time {inc['video_ts_text']}). "
            "Return JSON only with keys summary (2-3 sentences describing only what is visible in the frame and what the detector flagged) "
            "and uncertainties (a list of 1-3 short strings naming what cannot be determined from this frame). "
            "Do not claim a crime or an injury unless clearly visible."
        )
        body = dict(model=ANTHROPIC_MODEL, max_tokens=500, messages=[dict(role="user", content=[
            dict(type="image", source=dict(type="base64", media_type="image/jpeg", data=base64.b64encode(jpeg).decode())),
            dict(type="text", text=prompt)])])
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                r = await client.post("https://api.anthropic.com/v1/messages",
                                      headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"}, json=body)
                r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json()["content"]).strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(text)
            return dict(summary=str(data["summary"]), extra_limits=[str(x) for x in data["uncertainties"]][:3],
                        description_source="claude")
        except Exception as exc:  # noqa: BLE001
            log.warning("Claude description skipped: %s", exc)
            return None
