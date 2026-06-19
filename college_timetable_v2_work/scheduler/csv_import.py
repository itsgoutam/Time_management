"""
CSV Import Engine for Smart Timetable Generator
Handles: subjects, professors, rooms, sections, department_settings
"""
import csv
import io
from collections import defaultdict
import re
from .models import (
    Department, DepartmentSettings, Course, Room, Section,
    Professor, Subject, ProfessorOccupiedTime, ProfessorFixedSlot, TeachingAssignment,
    TimeSlot
)


def _resolve_professor(teacher_id, name, defaults):
    """Find (or create) the ONE canonical professor for this row, self-healing any
    pre-existing duplicates so a re-import never crashes or multiplies records.

    Identity: Teacher_id is the unique cross-department key when present; otherwise
    the name. If several rows already share that key (e.g. created by an older
    name-based import, possibly with different name spellings), they are collapsed
    into a single record — relations (timeslots, assignments, blocked/fixed times,
    department mappings) are moved onto the survivor and the rest deleted. Returns
    (professor, created_flag)."""
    if teacher_id:
        matches = list(Professor.objects.filter(professor_id=teacher_id).order_by('id'))
    else:
        matches = list(Professor.objects.filter(name=name, professor_id='').order_by('id'))

    if not matches:
        prof = Professor.objects.create(**defaults)
        return prof, True

    # Keep the richest record (most timetable usage / assignments / has a department).
    def _score(p):
        return (TimeSlot.objects.filter(professor=p).count(),
                p.assignments.count(),
                1 if p.department_id else 0,
                p.id)
    keep = max(matches, key=_score)
    for p in matches:
        if p.id == keep.id:
            continue
        TimeSlot.objects.filter(professor=p).update(professor=keep)
        p.assignments.all().update(professor=keep)
        p.occupied_times.all().update(professor=keep)
        p.fixed_slots.all().update(professor=keep)
        for d in p.departments.all():
            keep.departments.add(d)
        for subj in p.subject_set.all():
            subj.professors.remove(p)
            subj.professors.add(keep)
        p.delete()
    return keep, False


def _sem_digits(val):
    """Normalise a semester value to its leading digits: '4th' -> '4', '4' -> '4'."""
    m = re.match(r'\s*(\d+)', str(val or ''))
    return m.group(1) if m else _norm(val).lower()


def _norm(val):
    return (val or '').strip()


def _norm_up(val):
    return _norm(val).upper()


def _norm_key(key):
    """Canonicalise a CSV header so lookups are case/space-insensitive.
    'Teacher_name' -> 'teacher_name', 'Subject Name' -> 'subject_name'."""
    return (key or '').strip().lower().replace(' ', '_')


def _normalize_row(row):
    """Return a copy of a DictReader row keyed by canonical header names.
    Lets the importers read templates regardless of header casing/spacing."""
    out = {}
    for k, v in row.items():
        if k is None:
            continue
        out[_norm_key(k)] = v
    return out


def _is_note_row(text):
    """True for instructional 'Note:' rows embedded in the templates."""
    return _norm(text).lower().startswith('note')


def _parse_bool(val, default=False):
    return _norm_up(val) in ('YES', 'TRUE', '1', 'Y')


# ── File reading: accept CSV *or* Excel (.xlsx) transparently ───────────────────

def _cell_str(c):
    """Stringify one spreadsheet cell so xlsx rows look identical to CSV rows."""
    if c is None:
        return ''
    import datetime
    if isinstance(c, bool):
        return 'YES' if c else 'NO'
    if isinstance(c, float) and c.is_integer():
        return str(int(c))
    if isinstance(c, datetime.datetime):
        return c.strftime('%H:%M')
    if isinstance(c, datetime.time):
        return c.strftime('%H:%M')
    return str(c).strip()


class _XlsxReader:
    """Reads an .xlsx upload into the same shape csv.DictReader produces:
    iterable of {header: value} dicts, plus a .fieldnames list."""
    def __init__(self, raw):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        self.fieldnames = []
        self._rows = []
        headers = None
        for r in ws.iter_rows(values_only=True):
            vals = [_cell_str(c) for c in r]
            if headers is None:
                if not any(v.strip() for v in vals):
                    continue  # skip blank lead rows before the header
                headers = [h or '' for h in vals]
                self.fieldnames = headers
                continue
            if not any(v.strip() for v in vals):
                continue  # skip fully blank data rows
            self._rows.append({headers[i] if i < len(headers) else f'col{i}':
                               (vals[i] if i < len(vals) else '')
                               for i in range(max(len(headers), len(vals)))})
        wb.close()

    def __iter__(self):
        return iter(self._rows)


def _read_rows(file_obj):
    """Return a row reader for a CSV **or** Excel (.xlsx) upload. The result is
    iterable (dict rows) and exposes .fieldnames, so every importer can stay
    format-agnostic."""
    data = file_obj.read()
    raw = data.encode('utf-8') if isinstance(data, str) else data
    name = (getattr(file_obj, 'name', '') or '').lower()
    # Excel/OOXML files are ZIP archives — magic bytes 'PK\x03\x04'.
    is_xlsx = raw[:4] == b'PK\x03\x04' or name.endswith(('.xlsx', '.xlsm'))
    if is_xlsx:
        return _XlsxReader(raw)
    text = raw.decode('utf-8-sig', errors='replace')
    return csv.DictReader(io.StringIO(text))


# ── Department Settings CSV ────────────────────────────────────────────────────

def import_department_settings(file_obj, errors, warnings):
    """
    Expected columns: department, lunch_start_time, lunch_end_time, department_start_time
    lunch/start times as slot numbers 1-8 OR HH:MM strings mapped to slots.
    department_start_time: first slot for the day (default 1 = 9:00 AM).
    """
    # Maps slot START times to slot numbers
    START_TIME_TO_SLOT = {
        '9:00': 1, '09:00': 1,
        '9:50': 2, '09:50': 2,
        '10:40': 3,
        '11:30': 4,
        '12:20': 5,
        '1:10': 6, '01:10': 6, '13:10': 6,
        '2:00': 7, '14:00': 7,
        '2:50': 8, '14:50': 8,
        '3:40': 9, '15:40': 9,
    }
    END_TIME_TO_SLOT = {
        '9:50': 1, '09:50': 1,
        '10:40': 2,
        '11:30': 3,
        '12:20': 4,
        '1:10': 5, '01:10': 5, '13:10': 5,
        '2:00': 6, '02:00': 6, '14:00': 6,
        '2:50': 7, '02:50': 7, '14:50': 7,
        '3:40': 8, '03:40': 8, '15:40': 8,
        '4:30': 9, '04:30': 9, '16:30': 9,
    }

    def parse_start_slot(val):
        v = _norm(val)
        if not v:
            return None
        if v.isdigit():
            n = int(v)
            return n if 1 <= n <= 9 else None
        return START_TIME_TO_SLOT.get(v)

    def parse_end_slot(val):
        v = _norm(val)
        if not v:
            return None
        if v.isdigit():
            n = int(v)
            return n if 1 <= n <= 9 else None
        result = END_TIME_TO_SLOT.get(v)
        if result is None:
            result = START_TIME_TO_SLOT.get(v)
        return result

    created = 0
    reader = _read_rows(file_obj)
    for i, row in enumerate(reader, 1):
        row = _normalize_row(row)
        # Accept either 'Department_name' (current template) or legacy 'Department'.
        raw_dept = row.get('department_name', '') or row.get('department', '')
        if _norm(raw_dept).startswith('#') or _is_note_row(raw_dept):
            continue
        dept_name = _norm(raw_dept)
        if not dept_name:
            warnings.append(f"DeptSettings row {i}: missing department, skipped.")
            continue
        dept, _ = Department.objects.get_or_create(name=dept_name)

        ls_raw = _norm(row.get('lunch_start_time', ''))
        le_raw = _norm(row.get('lunch_end_time', ''))

        ls = parse_start_slot(ls_raw) if ls_raw else 5
        le = parse_end_slot(le_raw) if le_raw else None

        # ls == 0 means user entered break-gap time (1:10/2:00) → no slot to block
        if ls is None:
            ls = 5
            warnings.append(f"DeptSettings row {i}: unrecognised lunch_start_time '{ls_raw}', defaulting to slot 5.")
        if le is None or le == 0:
            le = ls if ls else 5

        # Parse department start time
        ds_raw = _norm(row.get('department_start_time', ''))
        dept_start = parse_start_slot(ds_raw) if ds_raw else 1
        if ds_raw and (dept_start is None or dept_start == 0):
            dept_start = 1
            warnings.append(f"DeptSettings row {i}: unrecognised department_start_time '{ds_raw}', defaulting to slot 1.")

        obj, _ = DepartmentSettings.objects.update_or_create(
            department=dept,
            defaults={
                'lunch_start_slot': ls if ls else 5,
                'lunch_end_slot': le if le else 5,
                'dept_start_slot': dept_start,
            }
        )
        created += 1
    return created
    return created


# ── Rooms CSV ──────────────────────────────────────────────────────────────────

def import_rooms(file_obj, errors, warnings, default_department=None):
    """
    Columns: department_name (optional), room_id, room_name, room_type,
             capacity, allowed_subjects
    room_type: classroom / lab
    department_name: the room's owning department. Falls back to the uploading
    Department Admin's department (default_department) when blank.
    """
    created = 0
    reader = _read_rows(file_obj)
    for i, row in enumerate(reader, 1):
        row = _normalize_row(row)
        if _is_note_row(row.get('room_id', '')) or _is_note_row(row.get('department_name', '')):
            continue
        name = _norm(row.get('room_name', ''))
        if not name:
            warnings.append(f"Rooms row {i}: missing room_name, skipped.")
            continue
        rtype_raw = _norm_up(row.get('room_type', 'CLASSROOM'))
        rtype = 'LAB' if 'LAB' in rtype_raw else 'CLASSROOM'
        capacity = int(row.get('capacity', 60) or 60)
        allowed = _norm(row.get('allowed_subjects', 'all')) or 'all'
        room_code = _norm(row.get('room_id', ''))   # e.g. MB-202 — sections' fixed_room refers to this
        # Owning department: from the CSV column, else the uploader's default.
        dept_name = _norm(row.get('department_name', ''))
        dept = None
        if dept_name:
            dept, _ = Department.objects.get_or_create(name=dept_name)
        elif default_department is not None:
            dept = default_department
        room, created_flag = Room.objects.get_or_create(name=name, defaults={
            'room_type': rtype, 'capacity': capacity, 'allowed_subjects': allowed,
            'department': dept, 'room_id': room_code,
        })
        if not created_flag:
            # Update if exists
            room.room_type = rtype
            room.capacity = capacity
            room.allowed_subjects = allowed
            if room_code:
                room.room_id = room_code
            if dept is not None:
                room.department = dept
            room.save()
        else:
            created += 1
    return created


# ── Professors CSV ─────────────────────────────────────────────────────────────

def _parse_block_slots(block_str):
    """
    Parse a block time string like "Tuesday,9:50 to 11:30" into
    (day, start_slot, end_slot) using SLOT_TIMES_DISPLAY boundaries.
    Returns None if parsing fails.
    """
    from .models import SLOT_TIMES_DISPLAY
    # Map start-time strings to slot numbers
    TIME_TO_SLOT = {
        '9:00': 1, '9:50': 2, '10:40': 3,
        '11:30': 4, '12:20': 5, '2:00': 6, '2:50': 7, '3:40': 8,
        '09:00': 1, '09:50': 2,
    }
    # Map end-time strings to slot numbers  
    END_TO_SLOT = {
        '9:50': 1, '10:40': 2, '11:30': 3,
        '12:20': 4, '1:10': 5, '13:10': 5,
        '2:50': 6, '3:40': 7, '4:30': 8,
        '09:50': 1, '10:40': 2,
    }
    DAY_NORM = {
        'MON': 'Monday', 'MONDAY': 'Monday',
        'TUE': 'Tuesday', 'TUESDAY': 'Tuesday',
        'WED': 'Wednesday', 'WEDNESDAY': 'Wednesday',
        'THU': 'Thursday', 'THURSDAY': 'Thursday',
        'FRI': 'Friday', 'FRIDAY': 'Friday',
    }
    s = block_str.strip()
    if not s:
        return None
    # Split on first comma to get day
    parts = s.split(',', 1)
    if len(parts) != 2:
        return None
    day_raw = parts[0].strip().upper()
    day = DAY_NORM.get(day_raw)
    if not day:
        return None
    time_part = parts[1].strip()
    # Support "9:50 to 11:30" or "9:50-11:30"
    for sep in [' to ', ' TO ', '-', '–']:
        if sep in time_part:
            t_parts = time_part.split(sep, 1)
            start_str = t_parts[0].strip()
            end_str   = t_parts[1].strip()
            start_slot = TIME_TO_SLOT.get(start_str)
            end_slot   = END_TO_SLOT.get(end_str)
            if start_slot and end_slot and start_slot <= end_slot:
                return (day, start_slot, end_slot)
    return None


def _resolve_assignment_dept(sem, sec_name, program, default_department, home_dept):
    """The department that OWNS a teaching assignment = the department of the section
    it targets (matched by semester + section name, disambiguated by program). Falls
    back to the uploading department, then the row's home department. This is what lets
    a shared professor's assignments be scoped per department on re-upload."""
    sem = (sem or '').strip()
    sn = (sec_name or '').strip().lower()
    if sem and sn:
        cands = [s for s in Section.objects.select_related('course__department')
                 if _sem_digits(s.year) == sem
                 and s.get_effective_section_name().strip().lower() == sn]
        if program:
            prog = program.strip().upper()
            pm = [s for s in cands if (s.program or '').strip().upper() == prog]
            cands = pm or cands
        for s in cands:
            d = getattr(getattr(s, 'course', None), 'department', None)
            if d:
                return d
    return default_department or home_dept


def import_professors(file_obj, errors, warnings, default_department=None):
    """
    Columns: professor_id, professor_name, max_workload_hours_per_week,
             specialization_subjects,
             SUB_CAN_TEACH_FOR_SPECIFIC_CLASS  (optional, format: DEPT,COURSE,YEAR,SEC)
             block_time_slot(day/time)          (optional, format: Tuesday,9:50 to 11:30)
    Multiple block slots can be separated by  |  e.g. "Monday,9:00 to 9:50|Friday,2:00 to 2:50"
    """
    created = 0
    # Professors whose workload was stated explicitly on at least one row. A blank
    # workload on later rows keeps the existing value; if stated more than once we
    # keep the MAXIMUM. (A teacher spans several rows — one per subject taught.)
    explicit_wl = set()
    cleared_assign = set()   # professors whose old TeachingAssignments were cleared this run
    reader = _read_rows(file_obj)
    # Normalise fieldnames so column lookup is case/space-insensitive
    raw_fields = reader.fieldnames or []
    norm_fields = [_norm_key(f) for f in raw_fields]
    BLOCK_KEY = next((f for f in norm_fields
                      if 'block' in f and 'time' in f), None)
    # 'Fixed_time_slot(day/time)' — the inverse of a block: the professor MUST
    # teach the row's subject at this day/time.
    FIXED_KEY = next((f for f in norm_fields
                      if 'fixed' in f and 'time' in f), None)
    # The "for specific class" column may be named SUB_CAN_TEACH_FOR_SPECIFIC_CLASS
    # or the legacy quoted "Dept Name,Prog Name,Sem,Sec" header (one comma-joined field).
    SPECIFIC_KEY = next((f for f in norm_fields
                         if 'sub_can_teach' in f or ('prog' in f and ('sem' in f or 'sec' in f))), None)
    # NEW format: the class is given in explicit columns instead of one combined
    # field — Program_name, Course_name, Semester, Section and (new) Group.
    HAS_EXPLICIT_CLASS = ('semester' in norm_fields and 'section' in norm_fields)

    for i, row in enumerate(reader, 1):
        row = _normalize_row(row)
        # Accept either the new 'Teacher_name' header or the legacy 'professor_name'.
        name = _norm(row.get('professor_name', '') or row.get('teacher_name', ''))
        # Skip comment / header / note rows
        if (not name or name.startswith('#')
                or name.lower() in ('professor_name', 'teacher_name') or _is_note_row(name)):
            continue
        # Workload may be blank on the extra rows of a multi-subject teacher.
        wl_raw = _norm(row.get('max_workload_hours_per_week', ''))
        max_wl = int(wl_raw) if wl_raw.isdigit() else 20
        # Teacher ID (doubles as the professor's login password).
        teacher_id = _norm(row.get('teacher_id', '') or row.get('professor_id', ''))
        # Home department (from the 'Department Name' column), used for admin scoping.
        # Falls back to the uploading Department Admin's own department.
        dept_name = _norm(row.get('department_name', ''))
        home_dept = None
        if dept_name:
            home_dept, _ = Department.objects.get_or_create(name=dept_name)
        elif default_department is not None:
            home_dept = default_department
        # Specialization subject: 'specialization_subjects' (legacy) or 'Subject Name' (new).
        spec = _norm(row.get('specialization_subjects', '') or row.get('subject_name', ''))

        # ── Determine the class this teacher takes (semester / section / group) ──
        # NEW format: explicit Program_name, Course_name, Semester, Section, Group
        # columns. LEGACY format: one combined "Dept,Prog,Sem,Sec" field.
        section_restr_entry = ''
        ta_sem = ta_sec = ta_program = ''
        ta_groups = []        # groups this row's assignment applies to ('' = whole section)
        if HAS_EXPLICIT_CLASS:
            p_prog   = _norm(row.get('program_name', ''))   # branch(es), e.g. "CSE,COE"
            p_course = _norm(row.get('course_name', ''))     # degree, e.g. "B.TECH"
            p_sem    = _norm(row.get('semester', ''))
            p_sec    = _norm(row.get('section', ''))
            p_group  = _norm_up(row.get('group', '')).replace(' ', ',')
            ta_sem = _sem_digits(p_sem)
            ta_sec = p_sec
            ta_program = p_prog
            restr = [x for x in (p_prog, p_course, p_sem, p_sec) if x]
            section_restr_entry = '|'.join(restr)
            glist = [g.strip() for g in p_group.split(',') if g.strip() in ('G1', 'G2', 'G3', 'G4')]
            # One specific group → assign to that group only; all/both/blank →
            # the whole section (stored as group '').
            ta_groups = [glist[0]] if len(glist) == 1 else ['']
        else:
            specific_class = _norm(
                row.get('sub_can_teach_for_specific_class', '')
                or (row.get(SPECIFIC_KEY, '') if SPECIFIC_KEY else ''))
            cls_parts = [p.strip() for p in specific_class.split(',') if p.strip()]
            if cls_parts:
                section_restr_entry = '|'.join(cls_parts[:4])
            ta_program = cls_parts[1] if len(cls_parts) >= 2 else ''
            ta_sem = _sem_digits(cls_parts[2]) if len(cls_parts) >= 3 else ''
            ta_sec = cls_parts[3] if len(cls_parts) >= 4 else ''
            ta_groups = ['']

        # Identity: prefer Teacher_id as the unique cross-department reference, so the
        # SAME teacher_id appearing under two departments is ONE shared professor (not
        # a duplicate). Fall back to name when no Teacher_id is given. _resolve_professor
        # also collapses any pre-existing duplicates so a re-import is self-healing.
        defaults = {
            'name': name,
            'max_workload_hours_per_week': max_wl,
            'specialization_subjects': spec,
            'section_restrictions': section_restr_entry,
            'professor_id': teacher_id,
            'department': home_dept,
        }
        prof, created_flag = _resolve_professor(teacher_id, name, defaults)
        # Map this professor to the row's department (cross-department sharing).
        if home_dept:
            prof.departments.add(home_dept)
        if created_flag:
            created += 1
            if wl_raw.isdigit():
                explicit_wl.add(prof.id)   # workload stated on the first row
        else:
            # A teacher can appear on several rows (one per subject they teach).
            # Workload rule: blank → keep existing; stated → keep the MAXIMUM of all
            # stated values (the first explicit value also replaces the default 20).
            if wl_raw.isdigit():
                if prof.id in explicit_wl:
                    prof.max_workload_hours_per_week = max(prof.max_workload_hours_per_week, max_wl)
                else:
                    prof.max_workload_hours_per_week = max_wl
                explicit_wl.add(prof.id)
            if teacher_id and not prof.professor_id:
                prof.professor_id = teacher_id
            # When matched by Teacher_id, the latest CSV's name wins so duplicate
            # spellings (e.g. "Kulbir Kaur" vs "Ms. Kulbir Kaur") converge.
            if teacher_id and name and prof.name != name:
                prof.name = name
            if home_dept and not prof.department_id:
                prof.department = home_dept
            if spec:
                existing = [s.strip() for s in prof.specialization_subjects.split(',') if s.strip()]
                if spec.lower() not in [e.lower() for e in existing]:
                    existing.append(spec)
                    prof.specialization_subjects = ', '.join(existing)
            if section_restr_entry:
                existing_r = [r.strip() for r in prof.section_restrictions.split(',') if r.strip()]
                if section_restr_entry not in existing_r:
                    existing_r.append(section_restr_entry)
                    prof.section_restrictions = ','.join(existing_r)
            prof.save()

        # ── Explicit teaching assignment (authoritative) ────────────────────
        # The row says: this teacher teaches `spec` for this Sem/Section/Group.
        # Record it so the timetable assigns exactly them. A different teacher may
        # be named per group (e.g. ML Lab G1 vs G2), so we key on group too.
        if spec and ta_sec:
            # Owning department = the section's department (so a SHARED professor's
            # assignments are scoped per department). Map the professor to it too, so
            # a teacher who teaches in another department becomes visible there.
            owning_dept = _resolve_assignment_dept(
                ta_sem, ta_sec, ta_program, default_department, home_dept)
            if owning_dept:
                prof.departments.add(owning_dept)
            # Rebuild ONLY this owning department's assignments for this teacher the
            # first time we see this (teacher, department) pair — never the others.
            ckey = (prof.id, owning_dept.id if owning_dept else None)
            if ckey not in cleared_assign:
                prof.assignments.filter(department=owning_dept).delete()
                cleared_assign.add(ckey)
            for g in ta_groups:
                ta_obj, _ = TeachingAssignment.objects.get_or_create(
                    professor=prof, subject_name=spec, semester=ta_sem,
                    section_name=ta_sec, group=g,
                    defaults={'department': owning_dept})
                if ta_obj.department_id != (owning_dept.id if owning_dept else None):
                    ta_obj.department = owning_dept
                    ta_obj.save(update_fields=['department'])

        # ── Block time slots ────────────────────────────────────────────────
        if BLOCK_KEY:
            block_raw = _norm(row.get(BLOCK_KEY, ''))
            if block_raw:
                # Support multiple blocks separated by |
                block_entries = [b.strip() for b in block_raw.split('|') if b.strip()]
                for entry in block_entries:
                    parsed = _parse_block_slots(entry)
                    if parsed:
                        day, start_slot, end_slot = parsed
                        ProfessorOccupiedTime.objects.get_or_create(
                            professor=prof,
                            day=day,
                            start_slot=start_slot,
                            end_slot=end_slot,
                            defaults={'activity_type': 'OTHER',
                                       'description': 'Blocked via CSV import'}
                        )
                    else:
                        warnings.append(
                            f"Professor '{name}' row {i}: could not parse block slot "
                            f"'{entry}'. Use format: Day,HH:MM to HH:MM "
                            f"(e.g. Tuesday,9:50 to 11:30)")

        # ── Fixed teaching slots (must-teach this subject at this time) ──────
        if FIXED_KEY:
            fixed_raw = _norm(row.get(FIXED_KEY, ''))
            if fixed_raw:
                for entry in [b.strip() for b in fixed_raw.split('|') if b.strip()]:
                    parsed = _parse_block_slots(entry)
                    if parsed:
                        day, start_slot, end_slot = parsed
                        ProfessorFixedSlot.objects.get_or_create(
                            professor=prof,
                            subject_name=spec,
                            section_restriction=section_restr_entry,
                            day=day,
                            start_slot=start_slot,
                            end_slot=end_slot,
                        )
                    else:
                        warnings.append(
                            f"Professor '{name}' row {i}: could not parse fixed slot "
                            f"'{entry}'. Use format: Day,HH:MM to HH:MM "
                            f"(e.g. Wednesday,9:50 to 11:30)")
    return created


# ── Sections CSV ───────────────────────────────────────────────────────────────

def import_sections(file_obj, errors, warnings):
    """
    Columns: department, year, section, group, fixed_room, course (optional),
             free_day (optional, e.g. Wednesday), class_count (optional, int),
             section_start_time (optional, e.g. 09:00 or 09:50)
    course values: B.TECH / BTECH / BE / M.TECH / MTECH  (default: BTECH)
    free_day: Monday / Tuesday / Wednesday / Thursday / Friday (leave blank for none)
    section_start_time: HH:MM format — overrides dept start time for this section only
    """
    # Semester 1–8. Accepts digits or ordinals: "3rd" → 3, "5th" → 5, etc.
    YEAR_MAP = {
        '1': '1', '1ST': '1', 'FIRST': '1', 'SEM1': '1', 'SEMESTER1': '1',
        '2': '2', '2ND': '2', 'SECOND': '2', 'SEM2': '2', 'SEMESTER2': '2',
        '3': '3', '3RD': '3', 'THIRD': '3', 'SEM3': '3', 'SEMESTER3': '3',
        '4': '4', '4TH': '4', 'FOURTH': '4', 'SEM4': '4', 'SEMESTER4': '4',
        '5': '5', '5TH': '5', 'FIFTH': '5', 'SEM5': '5', 'SEMESTER5': '5',
        '6': '6', '6TH': '6', 'SIXTH': '6', 'SEM6': '6', 'SEMESTER6': '6',
        '7': '7', '7TH': '7', 'SEVENTH': '7', 'SEM7': '7', 'SEMESTER7': '7',
        '8': '8', '8TH': '8', 'EIGHTH': '8', 'SEM8': '8', 'SEMESTER8': '8',
    }
    SECTION_MAP = {'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D', 'E': 'E'}
    COURSE_MAP = {
        'BTECH': 'BTECH', 'B.TECH': 'BTECH', 'B TECH': 'BTECH',
        'BE': 'BE',
        'MTECH': 'MTECH', 'M.TECH': 'MTECH', 'M TECH': 'MTECH',
        '': 'BTECH',
    }
    DAY_NORM = {
        'MON': 'Monday', 'MONDAY': 'Monday',
        'TUE': 'Tuesday', 'TUESDAY': 'Tuesday',
        'WED': 'Wednesday', 'WEDNESDAY': 'Wednesday',
        'THU': 'Thursday', 'THURSDAY': 'Thursday',
        'FRI': 'Friday', 'FRIDAY': 'Friday',
    }
    VALID_DAYS = {'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'}
    created = 0
    reader = _read_rows(file_obj)
    for i, row in enumerate(reader, 1):
        row = _normalize_row(row)
        # Accept either 'Department_name' (current template) or legacy 'Department'.
        dept_name = _norm(row.get('department_name', '') or row.get('department', ''))
        # Accept either 'year' (legacy) or 'Semester' (new template) for the year/sem field.
        year_raw = _norm_up(row.get('year', '') or row.get('semester', ''))
        sec_raw = _norm_up(row.get('section', 'A'))
        group_raw = _norm_up(row.get('group', 'G1'))
        fixed_room_name = _norm(row.get('fixed_room', ''))
        # Accept either 'Course_name' (current template) or legacy 'Course'.
        course_raw = _norm_up(row.get('course_name', '') or row.get('course', ''))
        # Parse free_day — accept column name 'free_day' or 'Free Day / Holiday'
        free_day_raw = _norm(row.get('free_day', '') or row.get('Free Day / Holiday', ''))
        free_day = DAY_NORM.get(free_day_raw.upper(), free_day_raw.capitalize() if free_day_raw else '')
        if free_day and free_day not in VALID_DAYS:
            warnings.append(f"Sections row {i}: unrecognised free_day '{free_day_raw}', ignored.")
            free_day = ''

        # Parse section_start_time column (e.g. "09:00", "09:50")
        TIME_TO_SLOT_SEC = {
            '9:00': 1, '09:00': 1, '9:50': 2, '09:50': 2,
            '10:40': 3, '11:30': 4, '12:20': 5,
            '1:10': 6, '13:10': 6, '2:00': 7, '14:00': 7,
            '2:50': 8, '14:50': 8, '3:40': 9, '15:40': 9,
        }
        start_time_raw = _norm(row.get('section_start_time', '') or row.get('Section Start Time', ''))
        section_start_slot = None
        if start_time_raw:
            section_start_slot = TIME_TO_SLOT_SEC.get(start_time_raw)
            if section_start_slot is None:
                warnings.append(f"Sections row {i}: unrecognised section_start_time '{start_time_raw}', ignored.")
        # class_count — number of students for capacity-based room assignment
        try:
            class_count = int(_norm(row.get('class_count', '0')) or 0)
        except ValueError:
            class_count = 0

        # Skip comment / sub-header / note rows
        if (not dept_name or dept_name.startswith('#')
                or dept_name.lower() in ('department', 'department_name')
                or _is_note_row(dept_name)):
            continue
        if not year_raw:
            warnings.append(f"Sections row {i}: missing year, skipped.")
            continue

        year_code = YEAR_MAP.get(year_raw, 'CUSTOM')
        custom_year = year_raw if year_code == 'CUSTOM' else ''
        sec_code = SECTION_MAP.get(sec_raw, 'CUSTOM')
        custom_sec = sec_raw if sec_code == 'CUSTOM' else ''
        group = group_raw if group_raw in ('G1', 'G2', 'G3', 'G4') else 'G1'
        course_code = COURSE_MAP.get(course_raw, 'BTECH')
        # Student branch/programme, e.g. CSE / COE (from the 'Program Name' column).
        program = _norm_up(row.get('program_name', '') or row.get('program', ''))

        dept, _ = Department.objects.get_or_create(name=dept_name)
        course, _ = Course.objects.get_or_create(department=dept, name=course_code)

        fixed_room = None
        if fixed_room_name:
            # Sections reference a room by its code (room_id, e.g. MB-202) or name.
            fixed_room = (Room.objects.filter(room_id__iexact=fixed_room_name).first()
                          or Room.objects.filter(name__iexact=fixed_room_name).first())
            if not fixed_room:
                warnings.append(f"Sections row {i}: fixed_room '{fixed_room_name}' not found.")

        try:
            sec, created_flag = Section.objects.get_or_create(
                course=course, year=year_code, section_name=sec_code,
                group=group, custom_year=custom_year, custom_section_name=custom_sec,
                defaults={'fixed_room': fixed_room, 'free_day': free_day, 'class_count': class_count,
                          'section_start_slot': section_start_slot, 'program': program}
            )
            if not created_flag and program and sec.program != program:
                sec.program = program
                sec.save(update_fields=['program'])
            if not created_flag:
                updated = False
                if fixed_room:
                    sec.fixed_room = fixed_room
                    updated = True
                if sec.free_day != free_day:
                    sec.free_day = free_day
                    updated = True
                # Update section_start_slot
                if sec.section_start_slot != section_start_slot:
                    sec.section_start_slot = section_start_slot
                    updated = True
                # Always update class_count on re-import
                if sec.class_count != class_count:
                    sec.class_count = class_count
                    updated = True
                if updated:
                    sec.save()
            if created_flag:
                created += 1
        except Exception as e:
            errors.append(f"Sections row {i}: {e}")
    return created


# ── Subjects CSV ───────────────────────────────────────────────────────────────

def import_subjects(file_obj, errors, warnings):
    """
    NEW FORMAT columns:
        subject_id, subject_name, sub_type, theory_per_week, lab_per_week,
        tutorial_per_week, allowed_groups, specialization_required, course, academic_year
    sub_type: DEPARTMENT (creates THEORY/LAB/TUTORIAL entries) or NPTL/NPTEL
    allowed_groups: G1 / G2 / G1 G2  (G1 G2 means Both)
    course: e.g. B.TECH  |  academic_year: e.g. 2ND, 3RD (optional section filters)

    LEGACY FORMAT (still supported):
        subject_id, subject_name, subject_type, lectures_per_week,
        allowed_groups, specialization_required
    """
    GROUP_MAP = {
        'G1': 'G1', 'G2': 'G2', 'G3': 'G3', 'G4': 'G4',
        'BOTH': 'BOTH', 'ALL': 'BOTH', '': 'BOTH',
        'G1 G2': 'BOTH', 'G1,G2': 'BOTH', 'G2 G1': 'BOTH',
        'G1 G2 G3': 'BOTH', 'G1 G2 G3 G4': 'BOTH',
    }
    LEGACY_TYPE_MAP = {
        'THEORY': 'THEORY', 'LAB': 'LAB', 'TUTORIAL': 'TUTORIAL',
        'NPTEL': 'NPTEL', 'NPTL': 'NPTEL',
    }
    # Semester 1–8 (matches Section.year values). "3rd" → 3, "5th" → 5, etc.
    YEAR_NORM = {
        '1': '1', '1ST': '1', 'FIRST': '1',
        '2': '2', '2ND': '2', 'SECOND': '2',
        '3': '3', '3RD': '3', 'THIRD': '3',
        '4': '4', '4TH': '4', 'FOURTH': '4',
        '5': '5', '5TH': '5', 'FIFTH': '5',
        '6': '6', '6TH': '6', 'SIXTH': '6',
        '7': '7', '7TH': '7', 'SEVENTH': '7',
        '8': '8', '8TH': '8', 'EIGHTH': '8',
    }

    subject_defs = []
    reader = _read_rows(file_obj)

    # Detect format by inspecting fieldnames
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    is_new_format = 'sub_type' in fieldnames or 'theory_per_week' in fieldnames

    for i, row in enumerate(reader, 1):
        row = _normalize_row(row)
        name = _norm(row.get('subject_name', ''))
        # Skip comment / sub-header / note rows
        if (not name or name.startswith('#')
                or name.lower() == 'subject_name' or _is_note_row(name)):
            continue

        code = _norm(row.get('subject_id', ''))
        allowed_groups_raw = _norm_up(row.get('allowed_groups', 'BOTH'))
        allowed_groups_raw = allowed_groups_raw.replace(',', ' ').strip()
        allowed_groups = GROUP_MAP.get(allowed_groups_raw, 'BOTH')
        spec_req = _parse_bool(row.get('specialization_required', 'No'))

        if is_new_format:
            # Sub_type vocabulary: REGULAR / ELECTIVE → normal theory/lab/tutorial
            # split; NPTEL/NPTL → NPTEL. (DEPARTMENT kept for backward compat.)
            sub_type_raw = _norm_up(row.get('sub_type', 'REGULAR'))
            is_nptl = sub_type_raw in ('NPTL', 'NPTEL')
            is_elective = sub_type_raw == 'ELECTIVE'

            def _safe_int(val, default=0):
                try:
                    return max(0, int(_norm(str(val)) or default))
                except (ValueError, TypeError):
                    return default

            # 'Theory_per_week_per_section' (current) or 'Theory_per_week' (older).
            theory = _safe_int(row.get('theory_per_week_per_section', 0)
                               or row.get('theory_per_week', 0))
            # Labs/tutorials: the current template states these PER GROUP and the
            # value is the number of weekly SESSIONS per group (e.g. Lab=1 → one
            # 2-slot lab block per group; Lab=2 → two, as for a major project).
            # Legacy templates used 'Lab_per_week' as contact HOURS (2 or 4), so a
            # 2-slot block already covers 2 hours → sessions = hours / 2.
            if 'lab_per_week_per_group' in fieldnames or 'tutorial_per_week_per_group' in fieldnames:
                lab = _safe_int(row.get('lab_per_week_per_group', 0))        # sessions/group
                tut = _safe_int(row.get('tutorial_per_week_per_group', 0))   # tutorials/group
            else:
                lab_hours = _safe_int(row.get('lab_per_week', 0))
                lab = max(1, lab_hours // 2) if lab_hours > 0 else 0
                tut = _safe_int(row.get('tutorial_per_week', 0))

            # 'Course_name' (new) or 'Course' (legacy) — the degree, e.g. B.TECH.
            course_filter = _norm(row.get('course', '') or row.get('course_name', ''))
            # Accept either 'academic_year' (legacy) or 'Semester' (new template).
            year_raw      = _norm_up(row.get('academic_year', '') or row.get('semester', ''))
            year_filter   = YEAR_NORM.get(year_raw, year_raw)
            dept_filter   = _norm(row.get('department_name', ''))
            # Student branches this subject is offered to, e.g. "CSE,COE" → {CSE, COE}.
            # This is the real student filter; Department_name is only the teaching
            # faculty's home department (which may differ, e.g. Applied Science).
            program_filter = {p.strip().upper() for p in
                              _norm(row.get('program_name', '')).replace(';', ',').split(',')
                              if p.strip()}

            base = {
                'code': code,
                'allowed_groups': allowed_groups,
                'specialization_required': spec_req,
                'course_filter': course_filter,
                'year_filter': year_filter,
                'dept_filter': dept_filter,
                'program_filter': program_filter,
                'is_elective': is_elective,
            }

            if is_nptl:
                # NPTEL weekly sessions = Theory_per_week when set (e.g. put 3 for a
                # 3-lecture NPTEL course); otherwise fall back to the tutorial/lab
                # count older templates used (Tutorial_per_week=1 → 1), default 1.
                total = theory if theory > 0 else ((tut + lab) or 1)
                subject_defs.append({**base, 'name': name,
                                      'subject_type': 'NPTEL',
                                      'lectures_per_week': total,
                                      'duration': 50})
            else:
                if theory > 0:
                    subject_defs.append({**base, 'name': name,
                                          'subject_type': 'THEORY',
                                          'lectures_per_week': theory,
                                          'duration': 50})
                if lab > 0:
                    lab_name = f"{name} Lab" if theory > 0 else name
                    # `lab` is the number of weekly 2-slot lab blocks PER GROUP
                    # (1 for a normal lab, 2 for e.g. a major project). Each group's
                    # section is scheduled independently, so this is per group.
                    subject_defs.append({**base, 'name': lab_name,
                                          'subject_type': 'LAB',
                                          'lectures_per_week': lab,
                                          'duration': 100})
                if tut > 0:
                    tut_name = f"{name} Tutorial" if (theory > 0 or lab > 0) else name
                    subject_defs.append({**base, 'name': tut_name,
                                          'subject_type': 'TUTORIAL',
                                          'lectures_per_week': tut,
                                          'duration': 50})
                if theory == 0 and lab == 0 and tut == 0:
                    warnings.append(
                        f"Subjects row {i}: '{name}' has zero lectures for all types, skipped.")
        else:
            # Legacy format
            stype_raw = _norm_up(row.get('subject_type', 'THEORY'))
            stype     = LEGACY_TYPE_MAP.get(stype_raw, 'THEORY')
            lectures  = int(row.get('lectures_per_week', 3) or 3)
            duration  = 100 if stype == 'LAB' else 50
            subject_defs.append({
                'name': name, 'code': code, 'subject_type': stype,
                'lectures_per_week': lectures, 'duration': duration,
                'allowed_groups': allowed_groups, 'specialization_required': spec_req,
                'course_filter': '', 'year_filter': '', 'dept_filter': '',
            })

    return subject_defs




# ── Explicit professor → subject linking (auto-assignment is OFF) ──────────────

def _norm_subj_name(s):
    """Canonicalise a subject name for tolerant matching: lowercase, collapse
    whitespace and remove spaces around hyphens, so '(PEC-3) - DL' matches
    '(PEC-3)- DL' and 'Operating Systems  Lab' matches 'Operating Systems Lab'."""
    s = (s or '').strip().lower()
    s = re.sub(r'\s*-\s*', '-', s)   # normalise spacing around hyphens
    s = re.sub(r'\s+', ' ', s)       # collapse remaining whitespace
    return s


def _norm_sec_name(s):
    return (s or '').strip().lower()


def _link_explicit_professors(subjects, warnings):
    """Attach each Subject to the professor explicitly named for it in the professors
    CSV (TeachingAssignment). Auto-assignment is OFF — a subject with no teacher named
    for its exact section/group is left unassigned (its professors are cleared).

    Matching is tolerant: subject names ignore spacing/punctuation differences and a
    section named 'COE' in the professors CSV matches the 'COE-1' section. THEORY/NPTEL
    share one teacher across G1+G2; a '... Tutorial' with no teacher of its own inherits
    its base subject's teacher. Reports any professor-CSV subject that is not defined in
    the subjects CSV (so it could not be assigned).
    """
    # (norm subject, sem digits, norm section, group) -> professor
    explicit_map = {}
    for ta in TeachingAssignment.objects.select_related('professor'):
        key = (_norm_subj_name(ta.subject_name), _sem_digits(ta.semester),
               _norm_sec_name(ta.section_name), (ta.group or '').strip().upper())
        explicit_map.setdefault(key, ta.professor)

    def _sec_match(target_sec, assign_sec):
        # Exact, or an unambiguous prefix at a '-' boundary ('coe' -> 'coe-1').
        return target_sec == assign_sec or target_sec.startswith(assign_sec + '-')

    def _lookup(nm, sem, sec_name, grp):
        ns = _norm_subj_name(nm)
        # Exact section, group-specific first then section-wide ('').
        for g in (grp, ''):
            p = explicit_map.get((ns, sem, sec_name, g))
            if p:
                return p
        # Section-spelling fallback (e.g. 'coe' assignment -> 'coe-1' section).
        for (ens, esem, esec, eg), prof in explicit_map.items():
            if ens == ns and esem == sem and eg in (grp, '') and _sec_match(sec_name, esec):
                return prof
        return None

    def _explicit_prof(subj_name, stype, sec):
        sem = _sem_digits(sec.year)
        sec_name = _norm_sec_name(sec.get_effective_section_name())
        grp = (getattr(sec, 'group', '') or '').strip().upper()
        p = _lookup(subj_name, sem, sec_name, grp)
        if p:
            return p
        # A tutorial with no teacher of its own inherits the base subject's teacher.
        if stype == 'TUTORIAL' and subj_name.lower().endswith(' tutorial'):
            return _lookup(subj_name[:-len(' Tutorial')], sem, sec_name, grp)
        return None

    # Process G1 before G2 so a G1-only theory teacher propagates to G2.
    GROUP_ORDER = {'G1': 0, 'G2': 1, 'G3': 2, 'G4': 3}
    subjects = sorted(subjects, key=lambda s: GROUP_ORDER.get(getattr(s.section, 'group', ''), 9))
    theory_shared = {}
    for subj in subjects:
        sec = subj.section
        if not sec:
            continue
        is_theory = subj.subject_type in ('THEORY', 'NPTEL')
        tkey = (sec.get_effective_section_name(), sec.year,
                getattr(getattr(sec, 'course', None), 'name', ''), subj.name)
        ex = _explicit_prof(subj.name, subj.subject_type, sec)
        if ex is None and is_theory and sec.group != 'G1' and tkey in theory_shared:
            ex = theory_shared[tkey]
        if ex is not None:
            subj.professors.set([ex])
            if is_theory and sec.group == 'G1':
                theory_shared[tkey] = ex
        else:
            subj.professors.clear()

    # ── Report professor-CSV subjects that are NOT defined in subjects.csv ────
    existing = {_norm_subj_name(n) for n in Subject.objects.values_list('name', flat=True)}
    missing = {}
    for ta in TeachingAssignment.objects.all():
        if _norm_subj_name(ta.subject_name) not in existing:
            label = f"Sem {ta.semester} {ta.section_name}".strip()
            missing.setdefault(ta.subject_name, set()).add(label)
    if missing:
        lines = "; ".join(f"{name} ({', '.join(sorted(secs))})"
                          for name, secs in sorted(missing.items()))
        warnings.append(
            f"{len(missing)} subject(s) are named in the professors CSV but not defined "
            f"in the subjects CSV, so their teacher(s) could not be assigned. Add them to "
            f"subjects.csv (matching the name exactly): {lines}")


# ── Full Import Orchestrator ───────────────────────────────────────────────────

def run_full_import(files_dict, default_department=None):
    """
    files_dict keys: 'subjects', 'professors', 'rooms', 'sections', 'dept_settings'
    All values are file-like objects (Django UploadedFile).
    default_department: when a Department Admin uploads, professors/rooms that do
    not name a department in the CSV are assigned to this department, keeping the
    data within that admin's scope. None for a full Admin (no default).
    Returns: dict with counts and error/warning lists.
    """
    errors = []
    warnings = []
    counts = {'subjects': 0, 'professors': 0, 'rooms': 0, 'sections': 0, 'dept_settings': 0}
    subject_defs = []

    # 1. Department settings (optional)
    if 'dept_settings' in files_dict and files_dict['dept_settings']:
        try:
            counts['dept_settings'] = import_department_settings(
                files_dict['dept_settings'], errors, warnings)
        except Exception as e:
            errors.append(f"DeptSettings import failed: {e}")

    # 2. Rooms
    if 'rooms' in files_dict and files_dict['rooms']:
        try:
            counts['rooms'] = import_rooms(files_dict['rooms'], errors, warnings,
                                           default_department=default_department)
        except Exception as e:
            errors.append(f"Rooms import failed: {e}")

    # 3. Sections — imported BEFORE professors so each teaching assignment's owning
    #    department can be resolved from the section it targets (this is what lets a
    #    shared professor keep their other department's assignments on a re-upload).
    if 'sections' in files_dict and files_dict['sections']:
        try:
            counts['sections'] = import_sections(files_dict['sections'], errors, warnings)
        except Exception as e:
            errors.append(f"Sections import failed: {e}")

    # 4. Professors
    if 'professors' in files_dict and files_dict['professors']:
        try:
            counts['professors'] = import_professors(files_dict['professors'], errors, warnings,
                                                     default_department=default_department)
        except Exception as e:
            errors.append(f"Professors import failed: {e}")

    # 5. Subjects (defines + links to all matching sections)
    if 'subjects' in files_dict and files_dict['subjects']:
        try:
            subject_defs = import_subjects(files_dict['subjects'], errors, warnings)
        except Exception as e:
            errors.append(f"Subjects import failed: {e}")

    # ── Build subjects from the subjects CSV, then assign explicit professors ──
    # Subject CREATION (and lab-room auto-assignment) is driven by the subjects CSV.
    # Professor assignment is a SEPARATE, explicit-only pass (auto-assignment is OFF)
    # in _link_explicit_professors — which also runs when ONLY the professors CSV is
    # uploaded (the elif below), so a professors-only upload still assigns everyone.
    if subject_defs:
        all_sections = list(Section.objects.select_related('course__department').order_by('course','year','section_name','group'))  # G1 before G2
        all_rooms = list(Room.objects.filter(room_type='LAB').all())

        def _build_subject(sdef, sec, all_rooms):
            lab_room = None
            if sdef['subject_type'] == 'LAB':
                for room in all_rooms:
                    if room.can_host_subject(sdef['name'], sdef['code']):
                        lab_room = room
                        break
            subj, created_flag = Subject.objects.get_or_create(
                name=sdef['name'], section=sec,
                defaults={
                    'code': sdef['code'],
                    'subject_type': sdef['subject_type'],
                    'lectures_per_week': sdef['lectures_per_week'],
                    'duration': sdef['duration'],
                    'allowed_groups': sdef['allowed_groups'],
                    'specialization_required': sdef['specialization_required'],
                    'is_elective': sdef.get('is_elective', False),
                    'lab_room': lab_room,
                }
            )
            if not created_flag:
                subj.code                    = sdef['code']
                subj.subject_type            = sdef['subject_type']
                subj.lectures_per_week       = sdef['lectures_per_week']
                subj.duration                = sdef['duration']
                subj.allowed_groups          = sdef['allowed_groups']
                subj.specialization_required = sdef['specialization_required']
                subj.is_elective             = sdef.get('is_elective', False)
                if lab_room:
                    subj.lab_room = lab_room
                subj.save()
            return subj, created_flag

        def _norm_dept(s):
            # Compare department names ignoring case, spaces and '&' spacing.
            return _norm_up(s).replace(' ', '').replace('&', '')

        def _section_matches(sdef, sec):
            ag            = sdef['allowed_groups']
            course_filter = _norm_up(sdef.get('course_filter', ''))
            year_filter   = _norm_up(sdef.get('year_filter', ''))
            dept_filter   = sdef.get('dept_filter', '')
            program_filter = sdef.get('program_filter') or set()
            dept_norm     = _norm_dept(dept_filter)
            prog_norms    = {_norm_dept(p) for p in program_filter}
            sec_program   = _norm_dept(getattr(sec, 'program', ''))
            # Program_name is a real STUDENT-BRANCH filter only when it differs from
            # the subject's own department (e.g. Applied Science dept, "CSE,COE"
            # program). When it merely repeats the department name (older single-
            # vocabulary templates), it is not a filter — match by department instead.
            prog_is_branch = bool(prog_norms) and prog_norms != {dept_norm}

            # Specific group filter — only assign to that group
            if ag in ('G1', 'G2', 'G3', 'G4') and sec.group != ag:
                return False
            # Branch/programme filter (PRIMARY when distinct): offers a subject to the
            # right students even when another department teaches it (Applied Science
            # → CSE). The section's branch must be one of the subject's branches.
            if prog_is_branch and sec_program:
                if sec_program not in prog_norms:
                    return False
            # Otherwise keep a subject within its own department's sections (preserves
            # single-/multi-department datasets where program == department).
            elif dept_filter:
                sec_dept = getattr(getattr(sec.course, 'department', None), 'name', '')
                if dept_norm != _norm_dept(sec_dept):
                    return False
            if course_filter:
                sec_course = _norm_up(getattr(sec.course, 'name', ''))
                if course_filter.replace('.', '') not in sec_course.replace('.', ''):
                    return False
            if year_filter:
                sec_year = _norm_up(getattr(sec, 'year', ''))
                if year_filter != sec_year:
                    return False
            return True
        # Create / refresh every subject that matches a section. No professor logic
        # here — teachers are attached by the explicit-only pass below.
        built_subjects = []
        for sdef in subject_defs:
            for sec in all_sections:
                if not _section_matches(sdef, sec):
                    continue
                subj, created_flag = _build_subject(sdef, sec, all_rooms)
                if created_flag:
                    counts['subjects'] += 1
                built_subjects.append(subj)
        # Explicit-only professor assignment over exactly the subjects just built.
        _link_explicit_professors(built_subjects, warnings)

    elif 'professors' in files_dict and files_dict['professors']:
        # Professors uploaded WITHOUT a subjects file: re-link teachers onto the
        # EXISTING subjects so a professors-only upload still assigns everyone.
        # Scoped to the uploading department when known (a Department Admin must
        # never re-link another department’s subjects).
        qs = Subject.objects.select_related('section__course__department')
        if default_department is not None:
            qs = qs.filter(section__course__department=default_department)
        _link_explicit_professors(list(qs), warnings)

    return counts, errors, warnings
