from django.db import models

SLOT_TIMES_DISPLAY = {
    1: '9:00–9:50',
    2: '9:50–10:40',
    3: '10:40–11:30',
    4: '11:30–12:20',
    5: '12:20–1:10',
    6: '1:10–2:00',
    7: '2:00–2:50',
    8: '2:50–3:40',
    9: '3:40–4:30',
}
SLOT_CHOICES = [(k, v) for k, v in SLOT_TIMES_DISPLAY.items()]
DAY_CHOICES = [
    ('Monday', 'Monday'), ('Tuesday', 'Tuesday'), ('Wednesday', 'Wednesday'),
    ('Thursday', 'Thursday'), ('Friday', 'Friday'),
]


class Department(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self): return self.name


class DepartmentSettings(models.Model):
    department = models.OneToOneField(Department, on_delete=models.CASCADE, related_name='settings')
    lunch_start_slot = models.IntegerField(default=5, choices=SLOT_CHOICES)
    lunch_end_slot   = models.IntegerField(default=5, choices=SLOT_CHOICES)
    dept_start_slot  = models.IntegerField(default=1, choices=SLOT_CHOICES,
                                           help_text='First slot of the day for this department (default: 1 = 9:00 AM)')
    working_days = models.CharField(max_length=200, default='Monday,Tuesday,Wednesday,Thursday,Friday')
    lecture_duration_minutes = models.IntegerField(default=50)

    def get_working_days(self):
        return [d.strip() for d in self.working_days.split(',') if d.strip()]

    def get_lunch_slots(self):
        return list(range(self.lunch_start_slot, self.lunch_end_slot + 1))

    def get_start_slot(self):
        return self.dept_start_slot if self.dept_start_slot else 1

    def __str__(self): return f"{self.department.name} Settings"

class Course(models.Model):
    COURSE_CHOICES = (
        ('BTECH', 'B.TECH'), ('BE', 'BE'), ('MTECH', 'M.TECH'), ('CUSTOM', 'Custom'),
    )
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='courses')
    name = models.CharField(max_length=10, choices=COURSE_CHOICES)
    custom_name = models.CharField(max_length=100, blank=True, default='')

    def get_display_name(self):
        if self.name == 'CUSTOM' and self.custom_name:
            return self.custom_name
        return self.get_name_display()

    def __str__(self):
        return f"{self.department.name} - {self.get_display_name()}"


class Room(models.Model):
    ROOM_TYPE_CHOICES = (
        ('CLASSROOM', 'Classroom'), ('LAB', 'Lab'),
    )
    name = models.CharField(max_length=100)
    # Short code from the CSV (e.g. MB-202). Sections reference their fixed room by this.
    room_id = models.CharField(max_length=50, blank=True, default='')
    room_type = models.CharField(max_length=10, choices=ROOM_TYPE_CHOICES, default='CLASSROOM')
    capacity = models.IntegerField(default=60)
    department = models.ForeignKey(
        'Department', on_delete=models.SET_NULL, null=True, blank=True, related_name='rooms')
    allowed_subjects = models.TextField(
        blank=True, default='all',
        help_text='"all" or comma-separated subject names/codes this lab can host.')

    def get_allowed_subjects_list(self):
        v = (self.allowed_subjects or '').strip()
        if not v or v.lower() == 'all':
            return None
        return [s.strip() for s in v.split(',') if s.strip()]

    def can_host_subject(self, subject_name, subject_code=''):
        allowed = self.get_allowed_subjects_list()
        if allowed is None:
            return True
        name_l = subject_name.lower()
        code_l = (subject_code or '').lower()
        return any(a.lower() in (name_l, code_l) for a in allowed)

    def __str__(self):
        return f"{self.name} ({self.get_room_type_display()}, cap:{self.capacity})"


class Section(models.Model):
    # Semesters 1–8 (the field is still named `year` internally for compatibility,
    # but it represents the semester and is displayed as "Semester N" everywhere).
    YEAR_CHOICES = (
        ('1', 'Semester 1'), ('2', 'Semester 2'), ('3', 'Semester 3'), ('4', 'Semester 4'),
        ('5', 'Semester 5'), ('6', 'Semester 6'), ('7', 'Semester 7'), ('8', 'Semester 8'),
        ('CUSTOM', 'Custom'),
    )
    SECTION_CHOICES = (
        ('A', 'Section A'), ('B', 'Section B'), ('C', 'Section C'),
        ('D', 'Section D'), ('E', 'Section E'), ('CUSTOM', 'Custom Section'),
    )
    GROUP_CHOICES = (('G1', 'Group 1'), ('G2', 'Group 2'), ('G3', 'Group 3'), ('G4', 'Group 4'),)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='sections')
    year = models.CharField(max_length=10, choices=YEAR_CHOICES)
    custom_year = models.CharField(max_length=50, blank=True, default='')
    section_name = models.CharField(max_length=20, choices=SECTION_CHOICES, default='A')
    custom_section_name = models.CharField(max_length=50, blank=True, default='')
    group = models.CharField(max_length=10, choices=GROUP_CHOICES)
    fixed_room = models.ForeignKey(
        Room, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fixed_sections',
        help_text='If set, theory lectures always use this room.')
    free_day = models.CharField(
        max_length=10, blank=True, default='',
        choices=[('', 'None')] + DAY_CHOICES,
        help_text='Weekly holiday for this section (e.g. Wednesday). No lectures scheduled on this day.'
    )
    section_start_slot = models.IntegerField(
        null=True, blank=True,
        choices=SLOT_CHOICES,
        help_text='Override start time for this section (leave blank to use department default).'
    )
    class_count = models.IntegerField(
        default=0,
        help_text='Number of students. Used to auto-select a room with sufficient capacity when no fixed room is set.'
    )

    def get_year_display_label(self):
        if self.year == 'CUSTOM' and self.custom_year:
            return self.custom_year
        return dict(self.YEAR_CHOICES).get(self.year, self.year)

    def get_effective_section_name(self):
        if self.section_name == 'CUSTOM' and self.custom_section_name:
            return self.custom_section_name
        if self.section_name == 'CUSTOM':
            return 'Custom'
        return self.section_name

    def get_section_display_label(self):
        return f"Section {self.get_effective_section_name()} — {self.get_group_display()}"

    def __str__(self):
        return f"{self.course} - {self.get_year_display_label()} - Sec {self.get_effective_section_name()} - {self.group}"

    class Meta:
        unique_together = ('course', 'year', 'section_name', 'group', 'custom_year', 'custom_section_name')


class Professor(models.Model):
    name = models.CharField(max_length=100)
    # Teacher ID from the CSV (e.g. CS001). Doubles as the professor's login password.
    professor_id = models.CharField(max_length=50, blank=True, default='')
    # Home department — used to scope which Department Admin manages this professor.
    department = models.ForeignKey(
        'Department', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='professors')
    email = models.EmailField(blank=True)
    max_workload_hours_per_week = models.IntegerField(default=20)
    specialization_subjects = models.TextField(blank=True, default='')
    # Stores parsed section restrictions from CSV SUB_CAN_TEACH_FOR_SPECIFIC_CLASS
    # Format: "DEPT|COURSE|YEAR|SEC-A,DEPT|COURSE|YEAR|SEC-B"  (comma-separated entries)
    section_restrictions = models.TextField(blank=True, default='')

    def get_specialization_list(self):
        if not self.specialization_subjects:
            return []
        return [s.strip().lower() for s in self.specialization_subjects.split(',') if s.strip()]

    def get_section_restrictions(self):
        """Returns list of (dept, course, year, section) tuples. Empty list means no restriction."""
        if not self.section_restrictions:
            return []
        result = []
        for entry in self.section_restrictions.split(','):
            parts = [p.strip().upper() for p in entry.split('|')]
            if len(parts) == 4:
                result.append(tuple(parts))
        return result

    def can_teach_section(self, section):
        """Returns True if professor is PREFERRED for this section.
        SUB_CAN_TEACH_FOR_SPECIFIC_CLASS is a preference/priority, NOT a hard restriction.
        Empty restriction = can teach anywhere (returns True always)."""
        restrictions = self.get_section_restrictions()
        if not restrictions:
            return True
        for dept, course, year, sec in restrictions:
            sec_dept = (section.course.department.name or '').upper()
            sec_course = (section.course.name or '').upper().replace('.', '')
            sec_year = (section.year or '').upper()
            sec_name = (section.section_name or '').upper()
            # Normalize year: "2 YEAR" -> "2ND", "2ND" -> "2ND"
            import re
            year_match = re.match(r'(\d+)', year)
            year_num = year_match.group(1) if year_match else ''
            sec_year_num = re.match(r'(\d+)', sec_year)
            sec_year_num = sec_year_num.group(1) if sec_year_num else ''
            course_norm = course.replace('.', '')
            if (dept in sec_dept and
                    course_norm in sec_course and
                    year_num == sec_year_num and
                    sec_name.startswith(sec.replace('SEC-', '').replace('SEC', ''))):
                return True
        return False

    def can_teach_specialized(self, subject_name, subject_code=''):
        """
        Match professor specialization against a subject name.

        Strategy (most-specific to least):
          1. Exact match            "OS Lab"  ↔  "OS Lab"
          2. Substring (either way) "OS Lab"  ↔  "OS"  (subject is a sub-string of spec)
                                    "OS"      ↔  "OS Lab" (spec is sub-string of subject)
          3. Token overlap          "OS Lab"  ↔  "OS Tutorial"  (share token "os")

        This means a professor whose specialization is "OS Lab" can teach
        "OS" (theory), "OS Lab", and "OS Tutorial" — i.e., anything in the
        same subject family — without requiring an exact name match.
        """
        specs = self.get_specialization_list()
        if not specs:
            return True  # no restriction — can teach everything
        name_l = subject_name.lower().strip()
        code_l = (subject_code or '').lower().strip()
        for spec in specs:
            # 1. Exact match
            if spec == name_l or (code_l and spec == code_l):
                return True
            # 2. Substring (bidirectional)
            if spec in name_l or name_l in spec:
                return True
            if code_l and (spec in code_l or code_l in spec):
                return True
            # 3. Token overlap — e.g. {"os","lab"} ∩ {"os","tutorial"} = {"os"}
            if set(spec.split()) & set(name_l.split()):
                return True
        return False

    def __str__(self):
        return self.name


class ProfessorOccupiedTime(models.Model):
    ACTIVITY_CHOICES = (
        ('MEETING', 'Meeting'), ('MENTORING', 'Student Mentoring'), ('OTHER', 'Other Activity'),
    )
    professor = models.ForeignKey(Professor, on_delete=models.CASCADE, related_name='occupied_times')
    day = models.CharField(max_length=10, choices=DAY_CHOICES)
    start_slot = models.IntegerField(choices=SLOT_CHOICES)
    end_slot = models.IntegerField(choices=SLOT_CHOICES)
    activity_type = models.CharField(max_length=20, choices=ACTIVITY_CHOICES, default='MEETING')
    description = models.CharField(max_length=200, blank=True)
    is_quick_block = models.BooleanField(default=False)

    def get_time_range_display(self):
        start = SLOT_TIMES_DISPLAY.get(self.start_slot, str(self.start_slot))
        end = SLOT_TIMES_DISPLAY.get(self.end_slot, str(self.end_slot))
        return start if self.start_slot == self.end_slot else f"{start} → {end}"

    def blocked_slots(self):
        return list(range(self.start_slot, self.end_slot + 1))

    def __str__(self):
        return f"{self.professor.name} — {self.day} {self.get_time_range_display()}"


class ProfessorFixedSlot(models.Model):
    """A day/time at which a professor MUST teach a specific subject for a
    specific class (from the professors CSV 'Fixed_time_slot(day/time)' column).

    The inverse of ProfessorOccupiedTime: instead of blocking the professor, it
    reserves them for that subject at that time. Currently the generator reserves
    the professor at this time; hard-pinning the actual class is a follow-up.
    """
    professor = models.ForeignKey(Professor, on_delete=models.CASCADE, related_name='fixed_slots')
    subject_name = models.CharField(max_length=100, blank=True, default='')
    # Target class, same format as Professor.section_restrictions: "DEPT|COURSE|YEAR|SEC"
    section_restriction = models.CharField(max_length=200, blank=True, default='')
    day = models.CharField(max_length=10, choices=DAY_CHOICES)
    start_slot = models.IntegerField(choices=SLOT_CHOICES)
    end_slot = models.IntegerField(choices=SLOT_CHOICES)

    def get_time_range_display(self):
        start = SLOT_TIMES_DISPLAY.get(self.start_slot, str(self.start_slot))
        end = SLOT_TIMES_DISPLAY.get(self.end_slot, str(self.end_slot))
        return start if self.start_slot == self.end_slot else f"{start} → {end}"

    def blocked_slots(self):
        return list(range(self.start_slot, self.end_slot + 1))

    def __str__(self):
        return f"{self.professor.name} fixed {self.subject_name} — {self.day} {self.get_time_range_display()}"


class Subject(models.Model):
    TYPE_CHOICES = (
        ('THEORY', 'Theoretical'), ('LAB', 'Lab'),
        ('TUTORIAL', 'Tutorial'), ('NPTEL', 'NPTEL (after 2:00 PM only)'),
    )
    ALLOWED_GROUPS_CHOICES = (
        ('G1', 'Group 1 Only'), ('G2', 'Group 2 Only'), ('G3', 'Group 3 Only'), ('G4', 'Group 4 Only'), ('BOTH', 'All Groups'),
    )
    code = models.CharField(max_length=20, blank=True, default='', verbose_name='Subject Code')
    name = models.CharField(max_length=100)
    subject_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    professors = models.ManyToManyField(Professor)
    duration = models.IntegerField(default=1)  # 1=50min, 2=100min (lab)
    lectures_per_week = models.IntegerField()
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='subjects', null=True, blank=True)
    lab_room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name='pinned_subjects')
    allowed_groups = models.CharField(max_length=10, choices=ALLOWED_GROUPS_CHOICES, default='BOTH')
    specialization_required = models.BooleanField(default=False)
    # Elective (Sub_type=ELECTIVE in the CSV): the semester's electives are run
    # in parallel at the same time slot in different rooms (a student picks one).
    is_elective = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class TimeSlot(models.Model):
    day = models.CharField(max_length=10)
    slot = models.IntegerField()
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    professor = models.ForeignKey(Professor, on_delete=models.CASCADE)
    section = models.ForeignKey(Section, on_delete=models.CASCADE, null=True, blank=True)
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name='timeslots')

    def __str__(self):
        return f"{self.day} Slot {self.slot}"


class RoomOccupiedTime(models.Model):
    PURPOSE_CHOICES = (
        ('WORKSHOP', 'Workshop / Seminar'), ('MAINTENANCE', 'Maintenance'),
        ('EXAM', 'Examination'), ('EVENT', 'College Event'), ('OTHER', 'Other'),
    )
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='occupied_times')
    day = models.CharField(max_length=10, choices=DAY_CHOICES)
    start_slot = models.IntegerField(choices=SLOT_CHOICES)
    end_slot = models.IntegerField(choices=SLOT_CHOICES)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES, default='OTHER')
    description = models.CharField(max_length=200, blank=True)

    def get_time_range_display(self):
        start = SLOT_TIMES_DISPLAY.get(self.start_slot, str(self.start_slot))
        end = SLOT_TIMES_DISPLAY.get(self.end_slot, str(self.end_slot))
        return start if self.start_slot == self.end_slot else f"{start} → {end}"

    def blocked_slots(self):
        return list(range(self.start_slot, self.end_slot + 1))

    def __str__(self):
        return f"{self.room.name} — {self.day} {self.get_time_range_display()}"


class CSVImportLog(models.Model):
    STATUS_CHOICES = (
        ('SUCCESS', 'Success'), ('PARTIAL', 'Partial Success'), ('FAILED', 'Failed'),
    )
    imported_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='SUCCESS')
    subjects_created = models.IntegerField(default=0)
    professors_created = models.IntegerField(default=0)
    rooms_created = models.IntegerField(default=0)
    sections_created = models.IntegerField(default=0)
    errors = models.TextField(blank=True, default='')
    warnings = models.TextField(blank=True, default='')

    def __str__(self):
        return f"Import {self.imported_at.strftime('%Y-%m-%d %H:%M')} — {self.get_status_display()}"


class StaffAccount(models.Model):
    """Login account for an Admin or a Department Admin.

    Admin       → full access to all departments (department is null).
    Dept Admin  → restricted strictly to a single department.
    Passwords are stored hashed (Django make_password / check_password).
    Professors and students are NOT stored here — professors authenticate
    against the Professor model (name + professor_id), students need no login.
    """
    ROLE_ADMIN = 'ADMIN'
    ROLE_DEPT_ADMIN = 'DEPT_ADMIN'
    ROLE_CHOICES = (
        (ROLE_ADMIN, 'Administrator'),
        (ROLE_DEPT_ADMIN, 'Department Admin'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_DEPT_ADMIN)
    username = models.CharField(max_length=100, unique=True)
    password = models.CharField(max_length=255)  # hashed
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, null=True, blank=True,
        related_name='admins',
        help_text='Required for Department Admins; leave blank for full Admins.')
    created_at = models.DateTimeField(auto_now_add=True)

    def set_password(self, raw_password):
        from django.contrib.auth.hashers import make_password
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        from django.contrib.auth.hashers import check_password
        return check_password(raw_password, self.password)

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    def __str__(self):
        scope = 'all departments' if self.is_admin else (self.department.name if self.department else 'no dept')
        return f"{self.username} ({self.get_role_display()} — {scope})"
