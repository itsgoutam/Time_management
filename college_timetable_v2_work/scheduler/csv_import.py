"""
CSV Import Engine for Smart Timetable Generator
Handles: subjects, professors, rooms, sections, department_settings
"""
import csv
import io
from collections import defaultdict
from .models import (
    Department, DepartmentSettings, Course, Room, Section,
    Professor, Subject, ProfessorOccupiedTime
)


def _norm(val):
    return (val or '').strip()


def _norm_up(val):
    return _norm(val).upper()


def _parse_bool(val, default=False):
    return _norm_up(val) in ('YES', 'TRUE', '1', 'Y')


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
    reader = csv.DictReader(io.TextIOWrapper(file_obj, encoding='utf-8-sig'))
    for i, row in enumerate(reader, 1):
        raw_dept = row.get('department', '')
        if _norm(raw_dept).startswith('#'):
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

def import_rooms(file_obj, errors, warnings):
    """
    Columns: room_id, room_name, room_type, capacity, allowed_subjects
    room_type: classroom / lab
    """
    created = 0
    reader = csv.DictReader(io.TextIOWrapper(file_obj, encoding='utf-8-sig'))
    for i, row in enumerate(reader, 1):
        name = _norm(row.get('room_name', ''))
        if not name:
            warnings.append(f"Rooms row {i}: missing room_name, skipped.")
            continue
        rtype_raw = _norm_up(row.get('room_type', 'CLASSROOM'))
        rtype = 'LAB' if 'LAB' in rtype_raw else 'CLASSROOM'
        capacity = int(row.get('capacity', 60) or 60)
        allowed = _norm(row.get('allowed_subjects', 'all')) or 'all'
        room, created_flag = Room.objects.get_or_create(name=name, defaults={
            'room_type': rtype, 'capacity': capacity, 'allowed_subjects': allowed
        })
        if not created_flag:
            # Update if exists
            room.room_type = rtype
            room.capacity = capacity
            room.allowed_subjects = allowed
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


def import_professors(file_obj, errors, warnings):
    """
    Columns: professor_id, professor_name, max_workload_hours_per_week,
             specialization_subjects,
             SUB_CAN_TEACH_FOR_SPECIFIC_CLASS  (optional, format: DEPT,COURSE,YEAR,SEC)
             block_time_slot(day/time)          (optional, format: Tuesday,9:50 to 11:30)
    Multiple block slots can be separated by  |  e.g. "Monday,9:00 to 9:50|Friday,2:00 to 2:50"
    """
    created = 0
    reader = csv.DictReader(io.TextIOWrapper(file_obj, encoding='utf-8-sig'))
    # Normalise fieldnames so column lookup is case/space-insensitive
    raw_fields = reader.fieldnames or []
    field_map = {f.strip().lower().replace(' ', '_'): f for f in raw_fields}
    BLOCK_KEY = next((f for f in raw_fields
                      if 'block' in f.lower() and 'time' in f.lower()), None)

    for i, row in enumerate(reader, 1):
        name = _norm(row.get('professor_name', ''))
        # Skip comment / header rows
        if not name or name.startswith('#') or name.lower() == 'professor_name':
            continue
        max_wl = int(row.get('max_workload_hours_per_week', 20) or 20)
        spec = _norm(row.get('specialization_subjects', ''))
        specific_class = _norm(row.get('SUB_CAN_TEACH_FOR_SPECIFIC_CLASS', ''))

        # Parse SUB_CAN_TEACH_FOR_SPECIFIC_CLASS into pipe-separated restriction entries
        # Format in CSV: "CSE,BTECH,2 YEAR,SEC-A" → stored as "CSE|BTECH|2 YEAR|SEC-A"
        section_restr = ''
        if specific_class:
            parts = [p.strip() for p in specific_class.split(',')]
            if len(parts) == 4:
                section_restr = '|'.join(parts)
            elif len(parts) > 4:
                # Could be multiple entries separated differently – store as-is joined
                section_restr = '|'.join(parts[:4])

        prof, created_flag = Professor.objects.get_or_create(name=name, defaults={
            'max_workload_hours_per_week': max_wl,
            'specialization_subjects': spec,
            'section_restrictions': section_restr,
        })
        if not created_flag:
            prof.max_workload_hours_per_week = max_wl
            prof.specialization_subjects = spec
            prof.section_restrictions = section_restr
            prof.save()
        else:
            created += 1

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
    YEAR_MAP = {
        '1': '1ST', '1ST': '1ST', 'FIRST': '1ST',
        '2': '2ND', '2ND': '2ND', 'SECOND': '2ND',
        '3': '3RD', '3RD': '3RD', 'THIRD': '3RD',
        '4': '4TH', '4TH': '4TH', 'FOURTH': '4TH',
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
    reader = csv.DictReader(io.TextIOWrapper(file_obj, encoding='utf-8-sig'))
    for i, row in enumerate(reader, 1):
        dept_name = _norm(row.get('department', ''))
        year_raw = _norm_up(row.get('year', ''))
        sec_raw = _norm_up(row.get('section', 'A'))
        group_raw = _norm_up(row.get('group', 'G1'))
        fixed_room_name = _norm(row.get('fixed_room', ''))
        course_raw = _norm_up(row.get('course', ''))
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

        # Skip comment / sub-header rows
        if not dept_name or dept_name.startswith('#') or dept_name.lower() == 'department':
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

        dept, _ = Department.objects.get_or_create(name=dept_name)
        course, _ = Course.objects.get_or_create(department=dept, name=course_code)

        fixed_room = None
        if fixed_room_name:
            fixed_room = Room.objects.filter(name__iexact=fixed_room_name).first()
            if not fixed_room:
                warnings.append(f"Sections row {i}: fixed_room '{fixed_room_name}' not found.")

        try:
            sec, created_flag = Section.objects.get_or_create(
                course=course, year=year_code, section_name=sec_code,
                group=group, custom_year=custom_year, custom_section_name=custom_sec,
                defaults={'fixed_room': fixed_room, 'free_day': free_day, 'class_count': class_count, 'section_start_slot': section_start_slot}
            )
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
    YEAR_NORM = {
        '1ST': '1ST', 'FIRST': '1ST', '1': '1ST',
        '2ND': '2ND', 'SECOND': '2ND', '2': '2ND',
        '3RD': '3RD', 'THIRD': '3RD', '3': '3RD',
        '4TH': '4TH', 'FOURTH': '4TH', '4': '4TH',
    }

    subject_defs = []
    wrapper = io.TextIOWrapper(file_obj, encoding='utf-8-sig')
    reader = csv.DictReader(wrapper)

    # Detect format by inspecting fieldnames
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    is_new_format = 'sub_type' in fieldnames or 'theory_per_week' in fieldnames

    for i, row in enumerate(reader, 1):
        name = _norm(row.get('subject_name', ''))
        # Skip comment / sub-header rows
        if not name or name.startswith('#') or name.lower() == 'subject_name':
            continue

        code = _norm(row.get('subject_id', ''))
        allowed_groups_raw = _norm_up(row.get('allowed_groups', 'BOTH'))
        allowed_groups_raw = allowed_groups_raw.replace(',', ' ').strip()
        allowed_groups = GROUP_MAP.get(allowed_groups_raw, 'BOTH')
        spec_req = _parse_bool(row.get('specialization_required', 'No'))

        if is_new_format:
            sub_type_raw = _norm_up(row.get('sub_type', 'DEPARTMENT'))
            is_nptl = sub_type_raw in ('NPTL', 'NPTEL')

            def _safe_int(val, default=0):
                try:
                    return max(0, int(_norm(str(val)) or default))
                except (ValueError, TypeError):
                    return default

            theory = _safe_int(row.get('theory_per_week', 0))
            lab    = _safe_int(row.get('lab_per_week', 0))
            tut    = _safe_int(row.get('tutorial_per_week', 0))

            course_filter = _norm(row.get('course', ''))
            year_raw      = _norm_up(row.get('academic_year', ''))
            year_filter   = YEAR_NORM.get(year_raw, year_raw)

            base = {
                'code': code,
                'allowed_groups': allowed_groups,
                'specialization_required': spec_req,
                'course_filter': course_filter,
                'year_filter': year_filter,
            }

            if is_nptl:
                total = theory + lab + tut or 1
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
                'course_filter': '', 'year_filter': '',
            })

    return subject_defs




# ── Full Import Orchestrator ───────────────────────────────────────────────────

def run_full_import(files_dict):
    """
    files_dict keys: 'subjects', 'professors', 'rooms', 'sections', 'dept_settings'
    All values are file-like objects (Django UploadedFile).
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
            counts['rooms'] = import_rooms(files_dict['rooms'], errors, warnings)
        except Exception as e:
            errors.append(f"Rooms import failed: {e}")

    # 3. Professors
    if 'professors' in files_dict and files_dict['professors']:
        try:
            counts['professors'] = import_professors(files_dict['professors'], errors, warnings)
        except Exception as e:
            errors.append(f"Professors import failed: {e}")

    # 4. Sections
    if 'sections' in files_dict and files_dict['sections']:
        try:
            counts['sections'] = import_sections(files_dict['sections'], errors, warnings)
        except Exception as e:
            errors.append(f"Sections import failed: {e}")

    # 5. Subjects (defines + links to all matching sections)
    if 'subjects' in files_dict and files_dict['subjects']:
        try:
            subject_defs = import_subjects(files_dict['subjects'], errors, warnings)
        except Exception as e:
            errors.append(f"Subjects import failed: {e}")

    # Now link subject definitions to matching sections
    if subject_defs:
        all_sections = list(Section.objects.select_related('course__department').order_by('course','year','section_name','group'))  # G1 before G2
        all_professors = list(Professor.objects.all())
        all_rooms = list(Room.objects.filter(room_type='LAB').all())

        # ── Workload tracker: prof.id -> accumulated lectures assigned ──────
        # Tracks how many lectures each professor has been assigned so far.
        # Uses RATIO (assigned / max_capacity) for fair comparison — a prof
        # with 18hr max and 10 lectures is MORE loaded than a 20hr max prof
        # with the same 10 lectures.
        import_prof_load = defaultdict(int)
        BLEND_THRESHOLD = 0.85   # blend non-spec profs when spec profs are 85%+ loaded

        def _load_ratio(p):
            """Proportion of workload used: 0.0 = free, 1.0 = full."""
            cap = max(1, (p.max_workload_hours_per_week * 60) // 50)
            return import_prof_load[p.id] / cap

        # ── TWO-PASS ASSIGNMENT ───────────────────────────────────────────────
        #
        # PASS 1 — Specialized subjects processed first (sorted by priority):
        #           spec_required=True subjects come before non-spec subjects.
        #           Spec professors are GUARANTEED their own subject family first.
        #
        # PASS 2 — Remaining capacity goes to other subjects.
        #           ALL professors (including spec ones) are eligible so that
        #           leftover capacity is distributed evenly.
        #
        # Within each pass the least-loaded professor is always chosen.
        # Result: spec prof teaches their subject family first, then takes
        # on other subjects only if they still have capacity.

        # Generic type-tokens that should NOT count as domain matches.
        # "OS Lab" should NOT match "DBMS Lab" just because both have "lab".
        _GENERIC_TOKENS = {'lab', 'tutorial', 'theory', 'practical', 'workshop',
                           'nptel', 'nptl', 'seminar', 'project'}

        def _domain_tokens(text):
            """Return meaningful (non-generic) tokens from a subject/spec name."""
            return set(text.lower().split()) - _GENERIC_TOKENS

        def _strict_spec_match(prof, name, code=''):
            """
            Domain-aware spec match — prevents 'OS Lab' spec matching 'DBMS Lab'.

            Logic (most-specific first):
              1. Exact full match         'OS Lab' == 'OS Lab'
              2. Direct substring         'OS' in 'OS Lab'  OR  'OS Lab' in 'OS Tutorial'
              3. DOMAIN token overlap     domain('OS Lab') = {'os'}
                                          domain('OS Tutorial') = {'os'}  → overlap {'os'} ✓
                                          domain('DBMS Lab') = {'dbms'}   → NO overlap  ✗
            """
            specs = prof.get_specialization_list()
            if not specs:
                return False          # No spec list = no priority claim
            name_l = name.lower().strip()
            code_l = (code or '').lower().strip()
            for spec in specs:
                # 1. Exact match
                if spec == name_l or (code_l and spec == code_l):
                    return True
                # 2. Direct substring (bidirectional)
                if spec in name_l or name_l in spec:
                    return True
                if code_l and (spec in code_l or code_l in spec):
                    return True
                # 3. Domain token overlap (generic tokens excluded)
                spec_domain = _domain_tokens(spec)
                subj_domain = _domain_tokens(name_l)
                if spec_domain and subj_domain and spec_domain & subj_domain:
                    return True
            return False

        def _has_spec_match(sdef):
            name = sdef['name']
            code = sdef.get('code', '')
            return any(_strict_spec_match(p, name, code) for p in all_professors)

        def _assign_professor(subj, sdef, sec, eligible_profs):
            if not eligible_profs:
                return None
            # Pick professor with lowest load RATIO (not raw count).
            # Ensures fair distribution across professors with different max hours.
            chosen = min(eligible_profs, key=_load_ratio)
            subj.professors.set([chosen])
            import_prof_load[chosen.id] += sdef.get('lectures_per_week', 1)
            return chosen

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
                if lab_room:
                    subj.lab_room = lab_room
                subj.save()
            return subj, created_flag

        def _section_matches(sdef, sec):
            ag            = sdef['allowed_groups']
            course_filter = _norm_up(sdef.get('course_filter', ''))
            year_filter   = _norm_up(sdef.get('year_filter', ''))
            # Specific group filter — only assign to that group
            if ag in ('G1', 'G2', 'G3', 'G4') and sec.group != ag:
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

        # Sort: spec_required=True first, then subjects that have a spec-match
        # professor, then everything else.
        # This guarantees spec professors fill their own subjects before non-spec
        # subjects consume their remaining capacity.
        def _sdef_priority(s):
            if s['specialization_required']:
                return 0
            if _has_spec_match(s):
                return 1
            return 2

        subject_defs_sorted = sorted(subject_defs, key=_sdef_priority)

        # THEORY shared-professor map:
        # key = (section_name, year, course_name, subject_name)
        # value = professor assigned to G1 (G2 must reuse same prof — same physical lecture)
        theory_shared_prof = {}

        for sdef in subject_defs_sorted:
            for sec in all_sections:
                if not _section_matches(sdef, sec):
                    continue

                subj, created_flag = _build_subject(sdef, sec, all_rooms)

                name = sdef['name']
                code = sdef.get('code', '')

                # ── Build eligible professor pool ────────────────────────────
                #
                # RULE: Professors specialized for a subject always get
                #       FIRST PRIORITY for that subject.
                #       They may also teach non-spec subjects with remaining capacity.
                #
                # spec_profs : professors whose specialization covers this subject
                #              (flexible can_teach_specialized: "OS Lab" covers
                #               "OS", "OS Lab", "OS Tutorial" etc.)
                # non_spec   : everyone else — fallback only.

                # Use strict domain-aware match to avoid false positives like
                # "OS Lab" spec matching "DBMS Lab" via the generic "lab" token.
                spec_profs = [p for p in all_professors if _strict_spec_match(p, name, code)]
                non_spec   = [p for p in all_professors if p not in spec_profs]

                if spec_profs:
                    # Prefer spec professors who also match the section preference
                    pref   = [p for p in spec_profs if p.can_teach_section(sec)]
                    others = [p for p in spec_profs if p not in pref]
                    spec_pool = pref + others

                    # Check remaining capacity for each spec professor using ratio.
                    # Threshold 0.85 = prof still has ~15% capacity left.
                    # Non-spec professors are blended in when spec profs are near-full,
                    # preventing one specialized professor from carrying all sections.
                    spec_with_capacity = [p for p in spec_pool if _load_ratio(p) < 1.0]
                    spec_not_overloaded = [p for p in spec_pool if _load_ratio(p) < BLEND_THRESHOLD]

                    if spec_not_overloaded:
                        # Spec professors have good capacity — use only them
                        eligible_profs = spec_not_overloaded
                    elif spec_with_capacity:
                        # Spec profs near limit — blend in least-loaded non-spec profs
                        non_spec_light = sorted(non_spec, key=_load_ratio)[:2]
                        eligible_profs = spec_with_capacity + non_spec_light
                    else:
                        # All spec professors at workload limit — non-spec fallback
                        non_spec_sec = [p for p in non_spec if p.can_teach_section(sec)]
                        eligible_profs = non_spec_sec or non_spec or spec_pool
                else:
                    # No specialized professor for this subject.
                    # Pick from everyone, section-preferred first.
                    # _assign_professor will pick lowest ratio among eligible.
                    pref_all = [p for p in all_professors if p.can_teach_section(sec)]
                    eligible_profs = pref_all or all_professors

                # ── THEORY shared-professor logic ────────────────────────────
                # Theory lectures are shared by G1 and G2 in the same classroom.
                # Both sections MUST have the same professor — otherwise the
                # timetable generator picks G1's professor for both, making G2's
                # Subject.professors stale and causing workload report mismatches.
                #
                # Rule:
                #   G1 → assigned normally (adds to workload)
                #   G2 → reuses G1's professor WITHOUT adding extra workload
                #         (it's the same physical lecture, not an extra session)
                is_theory = sdef.get('subject_type') in ('THEORY', 'NPTEL')
                theory_key = (
                    getattr(sec, 'section_name', str(sec)),
                    getattr(sec, 'year', ''),
                    getattr(getattr(sec, 'course', None), 'name', ''),
                    name,
                )

                if is_theory and sec.group != 'G1' and theory_key in theory_shared_prof:
                    # Reuse G1's professor — same lecture, no extra workload
                    shared_prof = theory_shared_prof[theory_key]
                    subj.professors.set([shared_prof])
                    if created_flag:
                        counts['subjects'] += 1
                    continue

                if eligible_profs:
                    chosen = _assign_professor(subj, sdef, sec, eligible_profs)
                    if not chosen:
                        warnings.append(
                            "Subject '{}' ({}) — no professor found at all.".format(name, sec)
                        )
                    else:
                        # Record G1's professor for G2 to reuse
                        if is_theory and sec.group == 'G1':
                            theory_shared_prof[theory_key] = chosen
                else:
                    warnings.append(
                        "Subject '{}' ({}) — no professor found at all.".format(name, sec)
                    )

                if created_flag:
                    counts['subjects'] += 1

    return counts, errors, warnings
