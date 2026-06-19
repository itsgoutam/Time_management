import re
from django import forms
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from .models import Subject, Professor, Section, Course, Department, Room, ProfessorOccupiedTime


class DatalistInput(forms.TextInput):
    """A free-text input with an attached <datalist> of suggestions.

    Behaves like an editable combo-box: the user may pick one of the existing
    values (so names stay unified with the CSV / other records) OR type any
    custom value that matches the CSV data format. Used everywhere a field used
    to be a restrictive dropdown."""

    def __init__(self, suggestions=None, attrs=None):
        self.suggestions = [s for s in (suggestions or []) if s not in (None, '')]
        super().__init__(attrs)

    def set_suggestions(self, suggestions):
        self.suggestions = [s for s in (suggestions or []) if s not in (None, '')]

    def render(self, name, value, attrs=None, renderer=None):
        attrs = dict(attrs or {})
        list_id = attrs.get('list') or f'dl_{name}'
        attrs['list'] = list_id
        attrs.setdefault('autocomplete', 'off')
        field_html = super().render(name, value, attrs, renderer)
        options = format_html_join(
            '', '<option value="{}"></option>',
            ((str(s),) for s in self.suggestions))
        return mark_safe(
            format_html('{}<datalist id="{}">{}</datalist>', field_html, list_id, options))


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = '__all__'


class CourseForm(forms.ModelForm):
    custom_name = forms.CharField(
        max_length=100, required=False, label='Custom Course Name',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. BCA, BSc, Diploma...', 'id': 'id_custom_name'})
    )
    class Meta:
        model = Course
        fields = ['department', 'name', 'custom_name']

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get('name')
        custom_name = cleaned_data.get('custom_name', '').strip()
        if name == 'CUSTOM' and not custom_name:
            self.add_error('custom_name', 'Please enter a custom course name.')
        return cleaned_data


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ['name', 'room_type', 'capacity', 'department', 'allowed_subjects']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Room 101, CS Lab 1'}),
            'capacity': forms.NumberInput(attrs={'min': 1}),
            'allowed_subjects': forms.TextInput(attrs={
                'placeholder': 'all  OR  OS Lab, DBMS Lab, Python Lab',
            }),
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['room_type'].label = 'Type'
        self.fields['capacity'].help_text = 'Number of students this room can hold'
        self.fields['department'].required = False
        self.fields['department'].help_text = 'Optional: Assign to a department so it is prioritised during generation.'
        self.fields['department'].empty_label = '— No department (shared/general) —'
        self.fields['allowed_subjects'].required = False
        self.fields['allowed_subjects'].help_text = (
            'For labs: enter "all" to allow any subject, '
            'or comma-separated subject names/codes for restrictions. '
            'Ignored for classrooms.'
        )


class SectionForm(forms.ModelForm):
    # These four are free-text combo inputs (type any custom value, or pick an
    # existing one from the suggestions). They replace the old restrictive
    # dropdowns so any section name / semester / group / free-day that matches
    # the CSV format can be entered manually. clean() maps them to the model's
    # stored representation (e.g. a non-A–E name → CUSTOM + custom_section_name).
    year = forms.CharField(required=True, label='Semester',
        widget=DatalistInput(attrs={'id': 'id_year', 'placeholder': 'e.g. 3  (or 3rd, Summer Term)'}))
    section_name = forms.CharField(required=True, label='Section',
        widget=DatalistInput(attrs={'id': 'id_section_name', 'placeholder': 'e.g. A, I, CS-1, COE'}))
    group = forms.CharField(required=False, label='Group',
        widget=DatalistInput(attrs={'id': 'id_group', 'placeholder': 'e.g. G1'}))
    free_day = forms.CharField(required=False, label='Free Day / Holiday',
        widget=DatalistInput(attrs={'placeholder': 'e.g. Wednesday  (blank = none)'}))
    program = forms.CharField(required=False, label='Program / Branch',
        widget=DatalistInput(attrs={'placeholder': 'e.g. CSE, COE  (student branch)'}))

    class Meta:
        model = Section
        fields = ['course', 'year', 'custom_year', 'section_name', 'custom_section_name', 'group', 'program', 'fixed_room', 'free_day', 'section_start_slot']
        labels = {
            'fixed_room': 'Fixed Classroom (optional)',
            'section_start_slot': 'Section Start Time (optional)',
        }
        widgets = {
            'section_start_slot': forms.Select(attrs={'class': 'form-select'}),
            # Hidden helpers — populated from the combo inputs in clean().
            'custom_year': forms.HiddenInput(),
            'custom_section_name': forms.HiddenInput(),
        }

    # Standard values stored as-is; anything else becomes a CUSTOM record.
    _STD_YEARS = {'1', '2', '3', '4', '5', '6', '7', '8'}
    _STD_SECTIONS = {'A', 'B', 'C', 'D', 'E'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fixed_room'].required = False
        self.fields['fixed_room'].empty_label = '— No fixed room (auto-assign) —'
        self.fields['fixed_room'].help_text = (
            'If set, theory lectures for this section will always be assigned to this classroom.'
        )
        self.fields['fixed_room'].queryset = Room.objects.filter(room_type='CLASSROOM')
        self.fields['free_day'].required = False
        self.fields['section_start_slot'].required = False
        self.fields['section_start_slot'].empty_label = '— Use department default —'
        self.fields['custom_year'].required = False
        self.fields['custom_section_name'].required = False

        # Build suggestion lists from what already exists, so manual entries stay
        # unified with the imported data instead of drifting into near-duplicates.
        existing_secs, existing_groups = set(), set()
        for s in Section.objects.all():
            eff = s.get_effective_section_name()
            if eff and eff != 'Custom':
                existing_secs.add(eff)
            if s.group:
                existing_groups.add(s.group)
        sec_suggestions = sorted(existing_secs) + [c for c in ['A', 'B', 'C', 'D', 'E']
                                                   if c not in existing_secs]
        self.fields['section_name'].widget.set_suggestions(sec_suggestions)
        self.fields['year'].widget.set_suggestions(['1', '2', '3', '4', '5', '6', '7', '8'])
        self.fields['group'].widget.set_suggestions(
            sorted(existing_groups | {'G1', 'G2', 'G3', 'G4'}))
        self.fields['free_day'].widget.set_suggestions(
            ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'])
        existing_programs = sorted({s.program for s in Section.objects.all() if s.program})
        self.fields['program'].widget.set_suggestions(existing_programs or ['CSE', 'COE'])

        # When editing, show the human/CSV value (e.g. '3', 'CS-1') in the combo.
        inst = getattr(self, 'instance', None)
        if inst and inst.pk:
            self.initial['year'] = inst.custom_year if inst.year == 'CUSTOM' else inst.year
            self.initial['section_name'] = inst.get_effective_section_name()

    def clean(self):
        cleaned_data = super().clean()

        # Semester: '3' / '3rd' / 'Semester 3' → '3'; anything else → CUSTOM label.
        raw_year = (cleaned_data.get('year') or '').strip()
        if not raw_year:
            self.add_error('year', 'Please enter a semester.')
        else:
            m = re.match(r'\s*(\d+)', raw_year)
            if m and m.group(1) in self._STD_YEARS:
                cleaned_data['year'] = m.group(1)
                cleaned_data['custom_year'] = ''
            else:
                cleaned_data['year'] = 'CUSTOM'
                cleaned_data['custom_year'] = raw_year

        # Section: 'A'–'E' kept as-is; any other label (I, CS-1, COE…) → CUSTOM.
        raw_sec = (cleaned_data.get('section_name') or '').strip()
        if not raw_sec:
            self.add_error('section_name', 'Please enter a section name.')
        elif raw_sec.upper() in self._STD_SECTIONS:
            cleaned_data['section_name'] = raw_sec.upper()
            cleaned_data['custom_section_name'] = ''
        else:
            cleaned_data['section_name'] = 'CUSTOM'
            cleaned_data['custom_section_name'] = raw_sec

        # Normalise free day capitalisation (so 'wednesday' == 'Wednesday').
        fd = (cleaned_data.get('free_day') or '').strip()
        cleaned_data['free_day'] = fd.capitalize() if fd else ''
        return cleaned_data


class SubjectForm(forms.ModelForm):
    subject_type = forms.ChoiceField(
        choices=[
            ('THEORY', 'Theory (50 min)'),
            ('LAB', 'Lab (100 min — 2 consecutive slots)'),
            ('TUTORIAL', 'Tutorial (50 min — per group)'),
            ('NPTEL', 'NPTEL (50 min — after 2:00 PM only)'),
            ('ELECTIVE', 'Elective (50 min — runs parallel with other electives)'),
        ],
        widget=forms.Select(attrs={'id': 'id_subject_type', 'onchange': 'setDuration(this.value)'})
    )

    # Single professor assignment — only ONE professor per subject
    professor = forms.ModelChoiceField(
        queryset=Professor.objects.all().order_by('name'),
        required=False,
        empty_label='— Select a Professor —',
        label='Professor',
        help_text='Assign exactly one professor to teach this subject.',
    )

    # Multi-section checkbox field (used only for Add; edit keeps single FK)
    sections = forms.ModelMultipleChoiceField(
        queryset=Section.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Section(s)',
        help_text='Check all sections/groups this subject applies to. A separate subject entry will be created for each.',
    )

    class Meta:
        model = Subject
        # 'professors' (M2M) is intentionally excluded; handled via custom 'professor' field above
        fields = ['code', 'name', 'subject_type', 'duration', 'lectures_per_week', 'section', 'lab_room']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['duration'].widget.attrs['readonly'] = True
        self.fields['duration'].widget.attrs['id'] = 'id_duration'
        self.fields['code'].widget.attrs['placeholder'] = 'e.g. CS301, IT401'
        self.fields['lectures_per_week'].help_text = (
            'Sessions per week, per group. For a Lab this is the number of 2-slot '
            'lab blocks each group gets (e.g. 1, or 2 for a major project).')
        self.fields['lab_room'].required = False
        self.fields['lab_room'].empty_label = '— No pinned room (auto-assign) —'
        self.fields['lab_room'].help_text = 'For Lab subjects: optionally pin to a specific lab room.'
        # Only show lab rooms in the dropdown
        self.fields['lab_room'].queryset = Room.objects.filter(room_type='LAB')
        # Populate sections queryset
        self.fields['sections'].queryset = Section.objects.select_related(
            'course__department'
        ).order_by('course__department__name', 'course__name', 'year', 'section_name', 'group')
        # Make original 'section' FK not required — we use 'sections' instead for add
        self.fields['section'].required = False
        self.fields['section'].widget = forms.HiddenInput()
        if self.instance and self.instance.pk:
            if self.instance.subject_type == 'LAB':
                self.fields['duration'].initial = 100
            else:
                self.fields['duration'].initial = 50
            # An elective is stored as a 50-min THEORY with is_elective=True — show
            # it as "Elective" in the dropdown when editing.
            if getattr(self.instance, 'is_elective', False):
                self.fields['subject_type'].initial = 'ELECTIVE'
            # Pre-select the existing section for edit view
            if self.instance.section:
                self.fields['sections'].initial = [self.instance.section.pk]
            # Pre-select the single assigned professor for edit view
            first_prof = self.instance.professors.first()
            if first_prof:
                self.fields['professor'].initial = first_prof.pk

    def clean(self):
        cleaned = super().clean()
        # "Elective" is stored as a 50-min THEORY subject flagged is_elective, so it
        # runs in parallel with the semester's other electives. Remap before the
        # model validates subject_type against its (THEORY/LAB/TUTORIAL/NPTEL) choices.
        is_elective = cleaned.get('subject_type') == 'ELECTIVE'
        cleaned['is_elective'] = is_elective
        if is_elective:
            cleaned['subject_type'] = 'THEORY'
            cleaned['duration'] = 50
        return cleaned


class ProfessorOccupiedTimeForm(forms.ModelForm):
    class Meta:
        model = ProfessorOccupiedTime
        fields = ['professor', 'day', 'start_slot', 'end_slot', 'activity_type', 'description']
        widgets = {
            'description': forms.TextInput(attrs={'placeholder': 'e.g. HOD meeting, Department review'}),
        }
        labels = {
            'start_slot': 'From (slot)',
            'end_slot': 'To (slot, inclusive)',
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_slot')
        end = cleaned_data.get('end_slot')
        if start and end and end < start:
            self.add_error('end_slot', 'End slot must be equal to or after the start slot.')
        return cleaned_data


class ProfessorForm(forms.ModelForm):
    class Meta:
        model = Professor
        fields = ['name', 'professor_id', 'email', 'max_workload_hours_per_week', 'specialization_subjects']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g. Dr. Sharma'}),
            'professor_id': forms.TextInput(attrs={'placeholder': 'e.g. CS001'}),
            'email': forms.EmailInput(attrs={'placeholder': 'e.g. sharma@college.edu'}),
            'max_workload_hours_per_week': forms.NumberInput(attrs={'min': 1, 'max': 40, 'placeholder': '20'}),
            'specialization_subjects': forms.Textarea(attrs={
                'placeholder': 'e.g. Machine Learning, Deep Learning, CS501\n(comma-separated — leave blank for no restriction)',
                'rows': 3,
            }),
        }
        labels = {
            'professor_id': 'Teacher ID (login password)',
            'max_workload_hours_per_week': 'Max Workload (hours/week)',
            'specialization_subjects': 'Specialization Subjects (optional)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['professor_id'].required = False
        self.fields['professor_id'].help_text = (
            "The professor signs in with their name and this ID as the password. "
            "Must be unique enough to identify them.")


class RoomOccupiedTimeForm(forms.ModelForm):
    class Meta:
        model = __import__('scheduler.models', fromlist=['RoomOccupiedTime']).RoomOccupiedTime
        fields = ['room', 'day', 'start_slot', 'end_slot', 'purpose', 'description']
        widgets = {
            'description': forms.TextInput(attrs={'placeholder': 'e.g. Workshop, Exam, Maintenance'}),
        }
        labels = {
            'start_slot': 'From (slot)',
            'end_slot': 'To (slot, inclusive)',
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get('start_slot')
        end = cleaned_data.get('end_slot')
        if start and end and end < start:
            self.add_error('end_slot', 'End slot must be equal to or after the start slot.')
        return cleaned_data


class QuickProfessorBlockForm(forms.Form):
    """Lightweight form used inline in subject form for quick professor blocking."""
    professor = forms.ModelChoiceField(
        queryset=None,  # set in __init__
        required=True,
        widget=forms.Select(attrs={'class': 'qblock-prof-sel'}),
    )
    day = forms.ChoiceField(
        choices=__import__('scheduler.models', fromlist=['DAY_CHOICES']).DAY_CHOICES,
        widget=forms.Select(attrs={'class': 'qblock-day-sel'}),
    )
    start_slot = forms.ChoiceField(
        choices=__import__('scheduler.models', fromlist=['SLOT_CHOICES']).SLOT_CHOICES,
        widget=forms.Select(attrs={'class': 'qblock-slot-sel'}),
    )
    end_slot = forms.ChoiceField(
        choices=__import__('scheduler.models', fromlist=['SLOT_CHOICES']).SLOT_CHOICES,
        widget=forms.Select(attrs={'class': 'qblock-slot-sel'}),
        required=False,
        label='End Slot (optional)',
    )
    activity_type = forms.ChoiceField(
        choices=[('MEETING','Meeting'),('MENTORING','Student Mentoring'),('OTHER','Other')],
        initial='MEETING',
        widget=forms.Select(attrs={'class': 'qblock-act-sel'}),
    )

    def __init__(self, *args, **kwargs):
        from .models import Professor
        super().__init__(*args, **kwargs)
        self.fields['professor'].queryset = Professor.objects.all()


# ── CSV Upload Form ────────────────────────────────────────────────────────────

class CSVUploadForm(forms.Form):
    subjects_csv = forms.FileField(
        required=False, label='📚 Subjects CSV / Excel',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,.xlsx,.xlsm'}),
        help_text='Fields: Department_name (teaching faculty), Subject_id, Subject_name, Sub_type (REGULAR/ELECTIVE/NPTEL), Theory_per_week_per_section, Tutorial_per_week_per_group, Lab_per_week_per_group, Allowed_groups, Course_name, Program_name (student branch, e.g. CSE or "CSE,COE"), Semester'
    )
    professors_csv = forms.FileField(
        required=False, label='👨‍🏫 Professors CSV / Excel',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,.xlsx,.xlsm'}),
        help_text='Fields: Department_name, Teacher_id, Teacher_name, Max_Workload_Hours_per_week, Subject_name, Program_name, Course_name, Semester, Section, Group, Block_time_slot(day/time), Fixed_time_slot(day/time)'
    )
    rooms_csv = forms.FileField(
        required=False, label='🚪 Rooms CSV / Excel',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,.xlsx,.xlsm'}),
        help_text='Fields: Department_name, Room_id, Room_name, Room_type, Capacity, Allowed_Subjects'
    )
    sections_csv = forms.FileField(
        required=False, label='🏫 Sections CSV / Excel',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,.xlsx,.xlsm'}),
        help_text='Fields: Department_name, Semester, section, group, Fixed_room, Course_name, Program_name, Free_day, Class_Count, Day, Section_Start_time'
    )
    dept_settings_csv = forms.FileField(
        required=False, label='⚙️ Department Settings CSV / Excel (optional)',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,.xlsx,.xlsm'}),
        help_text='Fields: Department_name, Lunch_Start_time, Department_Start_time'
    )
    auto_generate = forms.BooleanField(
        required=False, initial=True, label='Auto-generate timetable after import',
        help_text='Generate timetable immediately after CSV import.'
    )
    clear_existing = forms.BooleanField(
        required=False, initial=False, label='Clear existing data before import',
        help_text='⚠️ Deletes all current subjects/sections/timetable before importing.'
    )

    def clean(self):
        cleaned_data = super().clean()
        files = [
            cleaned_data.get('subjects_csv'),
            cleaned_data.get('professors_csv'),
            cleaned_data.get('rooms_csv'),
            cleaned_data.get('sections_csv'),
            # The Super Admin may upload department settings on their own (set once),
            # so it counts as a valid upload by itself too.
            cleaned_data.get('dept_settings_csv'),
        ]
        if not any(files):
            raise forms.ValidationError('Please upload at least one CSV/Excel file.')
        return cleaned_data


class DepartmentSettingsForm(forms.ModelForm):
    class Meta:
        from scheduler.models import DepartmentSettings, SLOT_CHOICES
        model = __import__('scheduler.models', fromlist=['DepartmentSettings']).DepartmentSettings
        fields = ['dept_start_slot', 'lunch_start_slot', 'working_days']
        labels = {
            'dept_start_slot': 'Department Start Time (first slot)',
            'lunch_start_slot': 'Lunch Break',
            'working_days': 'Working Days (comma-separated)',
        }
        help_texts = {
            'dept_start_slot': 'First teaching slot of the day. Slots before this are skipped during scheduling.',
            'working_days': 'e.g. Monday,Tuesday,Wednesday,Thursday,Friday',
        }

from scheduler.models import TimeSlot, DAY_CHOICES, SLOT_CHOICES

class TimeSlotForm(forms.ModelForm):
    class Meta:
        model = TimeSlot
        fields = ['day', 'slot', 'professor', 'room']
        widgets = {
            'day': forms.Select(choices=DAY_CHOICES),
            'slot': forms.Select(choices=SLOT_CHOICES),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            dept_id = self.instance.section.course.department_id
            from .models import Professor, Room
            from django.db.models import Q
            self.fields['professor'].queryset = Professor.objects.filter(
                Q(department_id=dept_id) | Q(department__isnull=True)
            ).order_by('name')
            self.fields['room'].queryset = Room.objects.filter(
                Q(department_id=dept_id) | Q(department__isnull=True)
            ).order_by('name')
