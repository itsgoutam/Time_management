"""
Timetable conflict-validation engine.

Validates a generated timetable (the TimeSlot rows) against the hard and soft
constraints the reference outputs satisfy, and reports every violation. It is the
single source of truth used in three places:

  • after generation — to resolve/guarantee a conflict-free schedule and report,
  • on demand — the "Validate Timetable" page,
  • before export — as a guard so a conflicting schedule is never exported.

A co-taught lecture (the SAME subject taught to G1 and G2 together in one room at
one time) is NOT a conflict — it is one physical lecture. Electives are scheduled
in PARALLEL for a section (the student picks one), so several elective subjects in
the same section/slot are likewise NOT a section conflict.
"""
from collections import defaultdict

from .models import TimeSlot, DepartmentSettings, Professor

# Hard conflicts block export; the rest are advisory warnings.
HARD_KINDS = ('faculty', 'room', 'section')
SOFT_KINDS = ('capacity', 'workload', 'nptel_prelunch')


def _lunch_start_by_dept():
    """department_id -> first lunch slot (defaults to 6 = 1:10–2:00 when unset)."""
    out = {}
    for ds in DepartmentSettings.objects.all():
        out[ds.department_id] = ds.lunch_start_slot or 6
    return out


def find_conflicts(dept_id=None):
    """Return a dict of conflict lists for the whole timetable (or one department).

    Keys: faculty, room, section, capacity, workload, nptel_prelunch — plus
    `has_hard` (bool) and `total_hard` (int)."""
    qs = TimeSlot.objects.select_related(
        'subject', 'professor', 'room', 'section__course__department')
    if dept_id:
        qs = qs.filter(section__course__department_id=dept_id)
    rows = list(qs)

    res = {k: [] for k in HARD_KINDS + SOFT_KINDS}

    by_prof = defaultdict(list)
    by_room = defaultdict(list)
    by_sec = defaultdict(list)
    prof_slots = defaultdict(set)        # prof_id -> {(day, slot)} → contact hours

    for t in rows:
        if t.professor_id:
            by_prof[(t.professor_id, t.day, t.slot)].append(t)
            prof_slots[t.professor_id].add((t.day, t.slot))
        if t.room_id:
            by_room[(t.room_id, t.day, t.slot)].append(t)
        if t.section_id:
            by_sec[(t.section_id, t.day, t.slot)].append(t)

    def names(ts_list):
        return {t.subject.name for t in ts_list}

    # ── Faculty: one professor, one (day, slot), more than one distinct subject ──
    for (_pid, day, slot), lst in by_prof.items():
        if len(names(lst)) > 1:
            res['faculty'].append({
                'professor': lst[0].professor.name, 'day': day, 'slot': slot,
                'subjects': sorted(names(lst))})

    # ── Room: one room hosting more than one distinct subject at once ───────────
    for (_rid, day, slot), lst in by_room.items():
        if len(names(lst)) > 1:
            res['room'].append({
                'room': lst[0].room.name, 'day': day, 'slot': slot,
                'subjects': sorted(names(lst))})

    # ── Section: a section/group with >1 distinct NON-elective subject at once ──
    for (_sid, day, slot), lst in by_sec.items():
        non_elective = {t.subject.name for t in lst if not getattr(t.subject, 'is_elective', False)}
        if len(non_elective) > 1:
            res['section'].append({
                'section': str(lst[0].section), 'day': day, 'slot': slot,
                'subjects': sorted(non_elective)})

    # ── Capacity: section size exceeds the assigned room's capacity ─────────────
    seen_cap = set()
    for t in rows:
        if not (t.room_id and t.section_id):
            continue
        students = t.section.class_count or 0
        cap = t.room.capacity or 0
        if cap and students > cap:
            key = (t.section_id, t.room_id)
            if key in seen_cap:
                continue
            seen_cap.add(key)
            res['capacity'].append({
                'section': str(t.section), 'students': students,
                'room': t.room.name, 'capacity': cap})

    # ── Workload: scheduled contact hours exceed the professor's CSV maximum ────
    profs = {p.id: p for p in Professor.objects.all()}
    for pid, slots in prof_slots.items():
        p = profs.get(pid)
        if p and len(slots) > p.max_workload_hours_per_week:
            res['workload'].append({
                'professor': p.name, 'hours': len(slots),
                'max': p.max_workload_hours_per_week})

    # ── NPTEL placement preference: should be after lunch (advisory) ────────────
    lunch = _lunch_start_by_dept()
    for t in rows:
        if t.subject.subject_type == 'NPTEL':
            ls = lunch.get(getattr(getattr(t.section, 'course', None), 'department_id', None), 6)
            if t.slot < ls:
                res['nptel_prelunch'].append({
                    'subject': t.subject.name, 'section': str(t.section),
                    'day': t.day, 'slot': t.slot})

    res['has_hard'] = any(res[k] for k in HARD_KINDS)
    res['total_hard'] = sum(len(res[k]) for k in HARD_KINDS)
    res['total_soft'] = sum(len(res[k]) for k in SOFT_KINDS)
    return res


def summary_lines(res):
    """Short human-readable lines for flash messages / reports."""
    lines = []
    for f in res['faculty']:
        lines.append(f"Faculty clash: {f['professor']} — {f['day']} slot {f['slot']} "
                     f"({', '.join(f['subjects'])})")
    for r in res['room']:
        lines.append(f"Room clash: {r['room']} — {r['day']} slot {r['slot']} "
                     f"({', '.join(r['subjects'])})")
    for s in res['section']:
        lines.append(f"Section clash: {s['section']} — {s['day']} slot {s['slot']} "
                     f"({', '.join(s['subjects'])})")
    return lines
