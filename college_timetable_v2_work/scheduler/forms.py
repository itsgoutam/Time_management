from django import forms
from .models import Subject, Professor, Section, Course, Department, Room, ProfessorOccupiedTime


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
    class Meta:
        model = Section
        fields = ['course', 'year', 'custom_year', 'section_name', 'custom_section_name', 'group', 'fixed_room', 'free_day', 'section_start_slot']
        labels = {
            'section_name': 'Section',
            'group': 'Group',
            'custom_year': 'Custom Semester Label',
            'custom_section_name': 'Custom Section Name',
            'fixed_room': 'Fixed Classroom (optional)',
            'free_day': 'Free Day / Holiday',
            'section_start_slot': 'Section Start Time (optional)',
        }
        widgets = {
            'year': forms.Select(attrs={'class': 'form-select', 'id': 'id_year', 'onchange': 'toggleCustomYear()'}),
            'section_name': forms.Select(attrs={'class': 'form-select', 'id': 'id_section_name', 'onchange': 'toggleCustomSection()'}),
            'group': forms.Select(attrs={'class': 'form-select'}),
            'free_day': forms.Select(attrs={'class': 'form-select'}),
            'section_start_slot': forms.Select(attrs={'class': 'form-select'}),
            'custom_year': forms.TextInput(attrs={
                'placeholder': 'e.g. Sem 9, Summer Term',
                'id': 'id_custom_year',
            }),
            'custom_section_name': forms.TextInput(attrs={
                'placeholder': 'e.g. F, G, Alpha',
                'id': 'id_custom_section_name',
            }),
        }

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
        # In Add mode the groups come from the 'groups' checkboxes (one section per
        # group), not the single 'group' field — so it must not be required, or the
        # form never validates and the "Add" button silently does nothing.
        self.fields['group'].required = False

        # Populate the Section dropdown with the section names that actually exist
        # (from the uploaded CSV) — e.g. I, II, III — plus the standard A–E and a
        # "Custom" option. Selecting an existing name lets you add a group to it.
        existing = []
        for s in Section.objects.all():
            eff = s.get_effective_section_name()
            if eff and eff != 'Custom':
                existing.append(eff)
        opts, seen = [], set()
        for name in sorted(set(existing)) + ['A', 'B', 'C', 'D', 'E']:
            if name and name not in seen:
                seen.add(name)
                opts.append((name, f'Section {name}'))
        opts.append(('CUSTOM', '➕ Custom (type a new name)'))
        self.fields['section_name'].choices = opts
        # When editing a custom-named section, pre-select its effective name.
        inst = getattr(self, 'instance', None)
        if inst and inst.pk and inst.section_name == 'CUSTOM' and inst.custom_section_name:
            if inst.custom_section_name not in seen:
                opts.insert(0, (inst.custom_section_name, f'Section {inst.custom_section_name}'))
                self.fields['section_name'].choices = opts
            self.initial['section_name'] = inst.custom_section_name

    def clean(self):
        cleaned_data = super().clean()
        # A picked existing/custom section name (e.g. 'I', 'II') is stored as
        # CUSTOM + that name, matching how the CSV importer stores it. This also
        # keeps it valid against the model field's choices (A–E / CUSTOM).
        chosen = cleaned_data.get('section_name')
        if chosen and chosen not in ('A', 'B', 'C', 'D', 'E', 'CUSTOM'):
            cleaned_data['custom_section_name'] = chosen
            cleaned_data['section_name'] = 'CUSTOM'
        year = cleaned_data.get('year')
        custom_year = (cleaned_data.get('custom_year') or '').strip()
        section_name = cleaned_data.get('section_name')
        custom_section_name = (cleaned_data.get('custom_section_name') or '').strip()
        if year == 'CUSTOM' and not custom_year:
            self.add_error('custom_year', 'Please enter a custom semester label.')
        if section_name == 'CUSTOM' and not custom_section_name:
            self.add_error('custom_section_name', 'Please enter a custom section name.')
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
        required=False, label='📚 Subjects CSV',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv'}),
        help_text='Fields: Department_name, Subject_id, Subject_Name, Sub_type (REGULAR/ELECTIVE/NPTEL), Theory_per_week, Tutorial_per_week, Lab_per_week, Allowed_groups, Course, Program Name, Semester'
    )
    professors_csv = forms.FileField(
        required=False, label='👨‍🏫 Professors CSV',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv'}),
        help_text='Fields: Department Name, Teacher_id, Teacher_name, Max_Workload_Hours_per_week, Subject Name, "Dept Name,Prog Name,Sem,Sec", Block_time_slot(day/time), Fixed_time_slot(day/time)'
    )
    rooms_csv = forms.FileField(
        required=False, label='🚪 Rooms CSV',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv'}),
        help_text='Fields: Department_name, Room_id, Room_name, Room_type, Capacity, Allowed_Subjects'
    )
    sections_csv = forms.FileField(
        required=False, label='🏫 Sections CSV',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv'}),
        help_text='Fields: Department, Semester, section, group, Fixed_room, Course, Program Name, Free_day, Class_Count, Day, Section_Start_time'
    )
    dept_settings_csv = forms.FileField(
        required=False, label='⚙️ Department Settings CSV (optional)',
        widget=forms.ClearableFileInput(attrs={'accept': '.csv'}),
        help_text='Fields: Department, Lunch_Start_time, Department_Start_time'
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
        ]
        if not any(files):
            raise forms.ValidationError('Please upload at least one CSV file.')
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
