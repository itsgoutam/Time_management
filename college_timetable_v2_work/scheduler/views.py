from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Prefetch
from .models import (Subject, Professor, TimeSlot, Section, Course, Department,
                     Room, ProfessorOccupiedTime, RoomOccupiedTime, SLOT_TIMES_DISPLAY,
                     DepartmentSettings, CSVImportLog)
from .forms import (SubjectForm, ProfessorForm, SectionForm, CourseForm,
                    DepartmentForm, RoomForm, ProfessorOccupiedTimeForm,
                    RoomOccupiedTimeForm, QuickProfessorBlockForm, CSVUploadForm)
from .csv_import import run_full_import
import random
from io import BytesIO
from collections import defaultdict, Counter

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
SLOTS = [1, 2, 3, 4, 5, 6, 7, 8, 9]
SLOT_TIMES = {
    1: "9:00-9:50",   2: "9:50-10:40",  3: "10:40-11:30",
    4: "11:30-12:20", 5: "12:20-1:10",  6: "1:10-2:00",
    7: "2:00-2:50",   8: "2:50-3:40",   9: "3:40-4:30",
}
# NPTEL scheduled after lunch — slot 6 (1:10-2:00) is first post-lunch slot,
# slots 7,8,9 are after 2PM. All are valid. Sorted asc so slot 6 fills first.
NPTEL_SLOTS = [6, 7, 8, 9]
LAB_FORBIDDEN_START = [5, 8, 9]
GROUP_ONE_LAB_STARTS = [1, 3, 6, 7]    # G1: pre-lunch preferred, post-lunch fallback
GROUP_TWO_LAB_STARTS = [1, 3, 6, 7]    # G2: pre-lunch first, post-lunch fallback
# Both groups prefer pre-lunch labs so partner tutorials also stay pre-lunch.
# Room/professor busy checks prevent actual conflicts.


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_qr_png(url, label):
    import qrcode
    from PIL import Image, ImageDraw
    qr = qrcode.QRCode(version=3, box_size=8, border=3,
                        error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr.add_data(url); qr.make(fit=True)
    qr_img = qr.make_image(fill_color=(21, 101, 192), back_color=(255, 255, 255)).convert('RGB')
    qw, qh = qr_img.size; pad = 12; hdr_h = 30
    canvas_w = qw + pad * 2; canvas_h = qh + pad * 2 + hdr_h
    canvas = Image.new('RGB', (canvas_w, canvas_h), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, canvas_w, hdr_h], fill=(21, 101, 192))
    canvas.paste(qr_img, (pad, hdr_h + pad))
    draw.rectangle([0, 0, canvas_w - 1, canvas_h - 1], outline=(21, 101, 192), width=3)
    buf = BytesIO(); canvas.save(buf, format='PNG'); buf.seek(0)
    return buf


def _build_tt_data(section):
    data = {}
    for day in DAYS:
        data[day] = {}
        for slot in SLOTS:
            data[day][slot] = TimeSlot.objects.filter(
                day=day, slot=slot, section=section
            ).select_related('subject', 'professor', 'room').first()
    return data


# ─── Dashboard ────────────────────────────────────────────────────────────────

def dashboard(request):
    departments = Department.objects.prefetch_related(
        Prefetch('courses__sections',
            queryset=Section.objects.order_by('year', 'section_name', 'custom_year', 'custom_section_name', 'group'))
    ).all()
    professors = Professor.objects.prefetch_related('occupied_times').all()
    subjects = Subject.objects.select_related('section__course__department').all()
    sections = Section.objects.select_related('course__department').order_by('year', 'section_name', 'custom_year', 'custom_section_name', 'group')
    rooms = Room.objects.select_related('department').all()
    classrooms = rooms.filter(room_type='CLASSROOM')
    labs = rooms.filter(room_type='LAB')
    subjects_no_section = subjects.filter(section__isnull=True)
    room_occupied_counts = {r.id: r.occupied_times.count() for r in rooms}
    return render(request, 'dashboard.html', {
        'departments': departments, 'professors': professors,
        'subjects': subjects, 'sections': sections,
        'rooms': rooms, 'classrooms': classrooms,
        'labs': labs, 'subjects_no_section': subjects_no_section,
        'room_occupied_counts': room_occupied_counts,
    })


# ─── Department CRUD ─────────────────────────────────────────────────────────

def add_department(request):
    form = DepartmentForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, '✅ Department added.')
        return redirect('dashboard')
    return render(request, 'generic_form.html', {'form': form, 'title': 'Add Department', 'icon': '🏫'})

def edit_department(request, dept_id):
    dept = get_object_or_404(Department, id=dept_id)
    form = DepartmentForm(request.POST or None, instance=dept)
    if form.is_valid():
        form.save()
        messages.success(request, '✅ Department updated.')
        return redirect('dashboard')
    return render(request, 'generic_form.html', {'form': form, 'title': 'Edit Department', 'icon': '🏫', 'edit': True})

def delete_department(request, dept_id):
    dept = get_object_or_404(Department, id=dept_id)
    if request.method == 'POST':
        dept.delete()
        messages.success(request, f'🗑️ Department "{dept.name}" deleted.')
        return redirect('dashboard')
    return render(request, 'confirm_delete.html', {'object': dept, 'type': 'Department'})


# ─── Course CRUD ──────────────────────────────────────────────────────────────

def add_course(request):
    form = CourseForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('dashboard')
    return render(request, 'generic_form.html', {'form': form, 'title': 'Add Course', 'icon': '🎓'})

def edit_course(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    form = CourseForm(request.POST or None, instance=course)
    if form.is_valid():
        form.save()
        messages.success(request, '✅ Course updated.')
        return redirect('dashboard')
    return render(request, 'generic_form.html', {'form': form, 'title': 'Edit Course', 'icon': '🎓', 'edit': True})

def delete_course(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    if request.method == 'POST':
        course.delete()
        messages.success(request, '🗑️ Course deleted.')
        return redirect('dashboard')
    return render(request, 'confirm_delete.html', {'object': course, 'type': 'Course'})


# ─── Room CRUD ────────────────────────────────────────────────────────────────

def add_room(request):
    form = RoomForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, '✅ Room added.')
        return redirect('dashboard')
    return render(request, 'generic_form.html', {'form': form, 'title': 'Add Room / Lab', 'icon': '🚪'})

def edit_room(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    form = RoomForm(request.POST or None, instance=room)
    if form.is_valid():
        form.save()
        messages.success(request, '✅ Room updated.')
        return redirect('dashboard')
    return render(request, 'generic_form.html', {'form': form, 'title': 'Edit Room', 'icon': '🚪', 'edit': True})

def delete_room(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    if request.method == 'POST':
        room.delete()
        messages.success(request, f'🗑️ Room "{room.name}" deleted.')
        return redirect('dashboard')
    return render(request, 'confirm_delete.html', {'object': room, 'type': 'Room'})

def room_schedule(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    schedule = {day: {slot: None for slot in SLOTS} for day in DAYS}
    for ts in TimeSlot.objects.filter(room=room).select_related('subject', 'professor', 'section__course__department'):
        if ts.day in schedule and ts.slot in schedule[ts.day]:
            schedule[ts.day][ts.slot] = ts
    table = {}
    for day in DAYS:
        cells = []
        skip_next = False
        for i, slot in enumerate(SLOTS):
            if skip_next:
                skip_next = False
                cells.append({'ts': None, 'colspan': 1, 'skip': True})
                continue
            ts = schedule[day][slot]
            if ts and ts.subject.subject_type == 'LAB':
                next_slot = SLOTS[i + 1] if i + 1 < len(SLOTS) else None
                if next_slot:
                    next_ts = schedule[day].get(next_slot)
                    if next_ts and next_ts.subject == ts.subject and next_ts.section == ts.section:
                        cells.append({'ts': ts, 'colspan': 2, 'skip': False})
                        skip_next = True
                        continue
            cells.append({'ts': ts, 'colspan': 1, 'skip': False})
        table[day] = cells
    occupied_times = room.occupied_times.all().order_by('day', 'start_slot')
    occ_map = {day: {} for day in DAYS}
    for occ in occupied_times:
        if occ.day in occ_map:
            for s in occ.blocked_slots():
                occ_map[occ.day][s] = occ
    # Merge occ_map into table cells
    for day in DAYS:
        for cell in table[day]:
            cell['occupied'] = None
    for day in DAYS:
        for i, cell in enumerate(table[day]):
            slot_num = SLOTS[i] if not cell.get('skip') else None
            if slot_num and slot_num in occ_map[day]:
                cell['occupied'] = occ_map[day][slot_num]
    return render(request, 'room_schedule.html', {
        'room': room, 'table': table, 'days': DAYS, 'slots': SLOTS, 'slot_times': SLOT_TIMES,
        'occupied_times': occupied_times, 'slot_times_display': SLOT_TIMES_DISPLAY,
        'lunch_label': '12:20–1:10',
    })


# ─── Section CRUD ─────────────────────────────────────────────────────────────

def add_section(request):
    form = SectionForm(request.POST or None)
    if request.method == 'POST':
        selected_groups = request.POST.getlist('groups')
        if form.is_valid() and selected_groups:
            base = form.save(commit=False)
            created = 0
            skipped = 0
            for grp in selected_groups:
                if Section.objects.filter(
                    course=base.course, year=base.year,
                    section_name=base.section_name,
                    custom_year=base.custom_year,
                    custom_section_name=base.custom_section_name,
                    group=grp
                ).exists():
                    skipped += 1
                    continue
                Section.objects.create(
                    course=base.course, year=base.year,
                    section_name=base.section_name,
                    custom_year=base.custom_year,
                    custom_section_name=base.custom_section_name,
                    group=grp,
                    fixed_room=base.fixed_room,
                    free_day=base.free_day,
                    section_start_slot=base.section_start_slot,
                )
                created += 1
            if created:
                messages.success(request, f'✅ {created} group(s) created successfully.' + (f' {skipped} already existed.' if skipped else ''))
            else:
                messages.warning(request, '⚠️ All selected groups already exist for this section.')
            return redirect('dashboard')
        elif form.is_valid() and not selected_groups:
            form.add_error(None, 'Please select at least one group.')
    return render(request, 'section_form.html', {'form': form, 'title': 'Add Section / Group', 'icon': '👥'})

def edit_section(request, section_id):
    section = get_object_or_404(Section, id=section_id)
    form = SectionForm(request.POST or None, instance=section)
    if form.is_valid():
        form.save()
        messages.success(request, '✅ Section updated.')
        return redirect('dashboard')
    return render(request, 'section_form.html', {'form': form, 'title': 'Edit Section', 'icon': '👥', 'edit': True})

def delete_section(request, section_id):
    section = get_object_or_404(Section, id=section_id)
    if request.method == 'POST':
        section.delete()
        messages.success(request, '🗑️ Section deleted.')
        return redirect('dashboard')
    return render(request, 'confirm_delete.html', {'object': section, 'type': 'Section'})


# ─── Subject CRUD ─────────────────────────────────────────────────────────────

def add_subject(request):
    form = SubjectForm(request.POST or None)
    qblock_form = QuickProfessorBlockForm(prefix='qblock')
    if request.method == 'POST':
        if 'save_subject' in request.POST and form.is_valid():
            selected_sections = form.cleaned_data.get('sections')
            if selected_sections:
                # Create one Subject per selected section
                professor = form.cleaned_data.get('professor')  # single Professor instance
                created_count = 0
                for sec in selected_sections:
                    subj = Subject(
                        code=form.cleaned_data['code'],
                        name=form.cleaned_data['name'],
                        subject_type=form.cleaned_data['subject_type'],
                        duration=form.cleaned_data['duration'],
                        lectures_per_week=form.cleaned_data['lectures_per_week'],
                        section=sec,
                        lab_room=form.cleaned_data.get('lab_room'),
                    )
                    subj.save()
                    if professor:
                        subj.professors.set([professor])  # enforce single professor
                    created_count += 1
                messages.success(request, f'✅ Subject added for {created_count} section(s).')
            else:
                messages.warning(request, '⚠️ Please select at least one section.')
                professors_with_blocks = _get_professors_with_blocks()
                return render(request, 'subject_form.html', {
                    'form': form, 'qblock_form': qblock_form,
                    'professors_with_blocks': professors_with_blocks,
                })
            return redirect('dashboard')
        if 'add_quick_block' in request.POST:
            prof_id   = request.POST.get('qblock-professor')
            day       = request.POST.get('qblock-day', 'Monday')
            start     = int(request.POST.get('qblock-start_slot', 1))
            end_raw   = request.POST.get('qblock-end_slot', '')
            end       = int(end_raw) if end_raw else start
            act_type  = request.POST.get('qblock-activity_type', 'MEETING')
            if prof_id:
                prof = get_object_or_404(Professor, id=prof_id)
                if end < start:
                    end = start
                ProfessorOccupiedTime.objects.create(
                    professor=prof, day=day,
                    start_slot=start, end_slot=end,
                    activity_type=act_type,
                    description='[Quick Block from subject form]',
                    is_quick_block=True,
                )
                messages.success(request, f"✅ Quick block added for {prof.name} on {day}.")
            else:
                messages.warning(request, '⚠️ Please select a professor to block.')
    professors_with_blocks = _get_professors_with_blocks()
    return render(request, 'subject_form.html', {
        'form': form, 'qblock_form': qblock_form,
        'professors_with_blocks': professors_with_blocks,
    })

def edit_subject(request, subject_id):
    subject = get_object_or_404(Subject, id=subject_id)
    form = SubjectForm(request.POST or None, instance=subject)
    qblock_form = QuickProfessorBlockForm(prefix='qblock')
    if request.method == 'POST':
        if 'save_subject' in request.POST and form.is_valid():
            # For edit: use first selected section (or keep existing)
            selected_sections = form.cleaned_data.get('sections')
            subj = form.save(commit=False)
            if selected_sections:
                subj.section = list(selected_sections)[0]
            subj.save()
            # Enforce single professor assignment
            professor = form.cleaned_data.get('professor')
            if professor:
                subj.professors.set([professor])
            else:
                subj.professors.clear()
            messages.success(request, '✅ Subject updated.')
            return redirect('dashboard')
        if 'add_quick_block' in request.POST:
            prof_id   = request.POST.get('qblock-professor')
            day       = request.POST.get('qblock-day', 'Monday')
            start     = int(request.POST.get('qblock-start_slot', 1))
            end_raw   = request.POST.get('qblock-end_slot', '')
            end       = int(end_raw) if end_raw else start
            act_type  = request.POST.get('qblock-activity_type', 'MEETING')
            if prof_id:
                prof = get_object_or_404(Professor, id=prof_id)
                if end < start:
                    end = start
                ProfessorOccupiedTime.objects.create(
                    professor=prof, day=day,
                    start_slot=start, end_slot=end,
                    activity_type=act_type,
                    description='[Quick Block from subject form]',
                    is_quick_block=True,
                )
                messages.success(request, f"✅ Quick block added for {prof.name} on {day}.")
            else:
                messages.warning(request, '⚠️ Please select a professor to block.')
    professors_with_blocks = _get_professors_with_blocks()
    return render(request, 'subject_form.html', {
        'form': form, 'edit': True, 'qblock_form': qblock_form,
        'professors_with_blocks': professors_with_blocks,
    })

def delete_subject(request, subject_id):
    subject = get_object_or_404(Subject, id=subject_id)
    if request.method == 'POST':
        subject.delete()
        messages.success(request, '🗑️ Subject deleted.')
        return redirect('dashboard')
    return render(request, 'confirm_delete.html', {'object': subject, 'type': 'Subject'})


# ─── Professor CRUD ───────────────────────────────────────────────────────────

def add_professor(request):
    form = ProfessorForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('dashboard')
    return render(request, 'professor_form.html', {'form': form})

def edit_professor(request, professor_id):
    professor = get_object_or_404(Professor, id=professor_id)
    form = ProfessorForm(request.POST or None, instance=professor)
    if form.is_valid():
        form.save()
        messages.success(request, '✅ Professor updated.')
        return redirect('dashboard')
    return render(request, 'professor_form.html', {'form': form, 'edit': True})

def delete_professor(request, professor_id):
    professor = get_object_or_404(Professor, id=professor_id)
    if request.method == 'POST':
        professor.delete()
        messages.success(request, '🗑️ Professor deleted.')
        return redirect('dashboard')
    return render(request, 'confirm_delete.html', {'object': professor, 'type': 'Professor'})


# ─── Professor Occupied Time CRUD ─────────────────────────────────────────────

def add_occupied_time(request, professor_id):
    professor = get_object_or_404(Professor, id=professor_id)
    initial = {'professor': professor}
    form = ProfessorOccupiedTimeForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()
        messages.success(request, f'✅ Occupied time added for {professor.name}.')
        return redirect('professor_schedule', professor_id=professor_id)
    return render(request, 'occupied_time_form.html', {
        'form': form, 'professor': professor, 'edit': False,
    })

def edit_occupied_time(request, occupied_id):
    occ = get_object_or_404(ProfessorOccupiedTime, id=occupied_id)
    form = ProfessorOccupiedTimeForm(request.POST or None, instance=occ)
    if form.is_valid():
        form.save()
        messages.success(request, '✅ Occupied time updated.')
        return redirect('professor_schedule', professor_id=occ.professor_id)
    return render(request, 'occupied_time_form.html', {
        'form': form, 'professor': occ.professor, 'edit': True,
    })

def delete_occupied_time(request, occupied_id):
    occ = get_object_or_404(ProfessorOccupiedTime, id=occupied_id)
    prof_id = occ.professor_id
    if request.method == 'POST':
        occ.delete()
        messages.success(request, '🗑️ Occupied time deleted.')
        return redirect('professor_schedule', professor_id=prof_id)
    return render(request, 'confirm_delete.html', {
        'object': occ, 'type': 'Occupied Time Block',
        'cancel_url': f'/professor/{prof_id}/',
    })


# ─── Helper: professors with their quick blocks ────────────────────────────────
def _get_professors_with_blocks():
    from .models import Professor, ProfessorOccupiedTime, SLOT_TIMES_DISPLAY
    profs = Professor.objects.prefetch_related('occupied_times').all()
    result = []
    for p in profs:
        blocks = []
        for occ in p.occupied_times.all().order_by('day', 'start_slot'):
            blocks.append({
                'id': occ.id,
                'day': occ.day,
                'time_range': occ.get_time_range_display(),
                'activity': occ.get_activity_type_display(),
                'is_quick': occ.is_quick_block,
                'description': occ.description,
            })
        result.append({'professor': p, 'blocks': blocks})
    return result


# ─── AJAX: professor blocks for subject form ──────────────────────────────────
def api_professor_blocks(request, professor_id):
    import json
    professor = get_object_or_404(Professor, id=professor_id)
    blocks = []
    for occ in professor.occupied_times.all().order_by('day', 'start_slot'):
        blocks.append({
            'id': occ.id,
            'day': occ.day,
            'time_range': occ.get_time_range_display(),
            'activity': occ.get_activity_type_display(),
            'is_quick': occ.is_quick_block,
            'description': occ.description,
        })
    return HttpResponse(json.dumps({'professor': professor.name, 'blocks': blocks}),
                        content_type='application/json')


# ─── Quick Block delete (from subject form) ───────────────────────────────────
def delete_quick_block(request, occupied_id):
    occ = get_object_or_404(ProfessorOccupiedTime, id=occupied_id)
    if request.method == 'POST':
        occ.delete()
        messages.success(request, '🗑️ Quick block removed.')
    return redirect('dashboard')


# ─── Room Occupied Time CRUD ──────────────────────────────────────────────────
def add_room_occupied(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    initial = {'room': room}
    form = RoomOccupiedTimeForm(request.POST or None, initial=initial)
    if form.is_valid():
        form.save()
        messages.success(request, f'✅ Occupied time added for {room.name}.')
        return redirect('room_schedule', room_id=room_id)
    return render(request, 'room_occupied_form.html', {'form': form, 'room': room, 'edit': False})


def edit_room_occupied(request, occupied_id):
    occ = get_object_or_404(RoomOccupiedTime, id=occupied_id)
    form = RoomOccupiedTimeForm(request.POST or None, instance=occ)
    if form.is_valid():
        form.save()
        messages.success(request, '✅ Room occupied time updated.')
        return redirect('room_schedule', room_id=occ.room_id)
    return render(request, 'room_occupied_form.html', {'form': form, 'room': occ.room, 'edit': True})


def delete_room_occupied(request, occupied_id):
    occ = get_object_or_404(RoomOccupiedTime, id=occupied_id)
    room_id = occ.room_id
    if request.method == 'POST':
        occ.delete()
        messages.success(request, '🗑️ Room occupied time deleted.')
        return redirect('room_schedule', room_id=room_id)
    return render(request, 'confirm_delete.html', {
        'object': occ, 'type': 'Room Occupied Block',
        'cancel_url': f'/room/{room_id}/',
    })



# ─── Professor Schedule ───────────────────────────────────────────────────────

def professor_schedule(request, professor_id):
    professor = get_object_or_404(Professor, id=professor_id)
    occupied_times = ProfessorOccupiedTime.objects.filter(professor=professor).order_by('day', 'start_slot')

    # Build occupied slot map {day: {slot: occ_obj}}
    occupied_map = {day: {} for day in DAYS}
    for occ in occupied_times:
        if occ.day in occupied_map:
            for s in occ.blocked_slots():
                occupied_map[occ.day][s] = occ

    raw = {day: {slot: [] for slot in SLOTS} for day in DAYS}
    for ts in TimeSlot.objects.filter(professor=professor).select_related(
            'subject', 'section__course__department', 'room').order_by('day', 'slot'):
        if ts.day in raw and ts.slot in raw[ts.day]:
            raw[ts.day][ts.slot].append(ts)

    # ── Include G2 timeslots for shared THEORY/NPTEL lectures ────────────────
    # G1 and G2 attend the same physical lecture with the same professor.
    # If professor has a G1 theory timeslot, the matching G2 timeslot (same
    # slot / same subject name / same section_name+year+course) should also
    # appear on their schedule — even if the G2 timeslot.professor FK wasn't
    # updated (e.g. old data). We look them up and merge them in.
    existing_ts_ids = set()
    for day in DAYS:
        for slot in SLOTS:
            for ts in raw[day][slot]:
                existing_ts_ids.add(ts.id)

    # Build lookup: (day, slot, subject_name, section_name, year, course_id) → ts
    for ts in TimeSlot.objects.filter(professor=professor).select_related(
            'subject', 'section__course__department', 'room'):
        if ts.subject.subject_type not in ('THEORY', 'NPTEL'):
            continue
        sec = ts.section
        # Find the partner group timeslot for the same slot+subject+section
        partner_group = 'G2' if sec.group == 'G1' else 'G1'
        partner_ts_qs = TimeSlot.objects.filter(
            day=ts.day, slot=ts.slot,
            subject__name=ts.subject.name,
            section__section_name=sec.section_name,
            section__year=sec.year,
            section__course_id=sec.course_id,
            section__group=partner_group,
        ).select_related('subject', 'section__course__department', 'room')
        for pts in partner_ts_qs:
            if pts.id not in existing_ts_ids and pts.day in raw and pts.slot in raw[pts.day]:
                raw[pts.day][pts.slot].append(pts)
                existing_ts_ids.add(pts.id)

    table = {}
    for day in DAYS:
        cells = []
        skip_next = False
        for i, slot in enumerate(SLOTS):
            if skip_next:
                skip_next = False
                cells.append({'entries': [], 'colspan': 1, 'skip': True, 'occupied': None})
                continue
            entries = raw[day][slot]
            occ = occupied_map[day].get(slot)
            seen = {}
            deduped = []
            for ts in entries:
                key = ts.subject_id
                if key not in seen:
                    seen[key] = {'ts': ts, 'sections': [ts.section]}
                    deduped.append(seen[key])
                else:
                    seen[key]['sections'].append(ts.section)
            is_lab_pair = False
            if deduped and deduped[0]['ts'].subject.subject_type == 'LAB':
                next_slot = SLOTS[i + 1] if i + 1 < len(SLOTS) else None
                if next_slot and deduped[0]['ts'].subject_id in {t.subject_id for t in raw[day][next_slot]}:
                    is_lab_pair = True
            if is_lab_pair:
                cells.append({'entries': deduped, 'colspan': 2, 'skip': False, 'occupied': occ})
                skip_next = True
            else:
                cells.append({'entries': deduped, 'colspan': 1, 'skip': False, 'occupied': occ})
        table[day] = cells

    total_slots = sum(1 for d in DAYS for c in table[d] if not c['skip'] and c['entries'])
    total_theory = sum(1 for d in DAYS for c in table[d]
                       if not c['skip'] and c['entries']
                       and c['entries'][0]['ts'].subject.subject_type in ('THEORY', 'NPTEL'))
    total_lab = sum(1 for d in DAYS for c in table[d]
                    if not c['skip'] and c['entries']
                    and c['entries'][0]['ts'].subject.subject_type == 'LAB')
    total_tutorial = sum(1 for d in DAYS for c in table[d]
                         if not c['skip'] and c['entries']
                         and c['entries'][0]['ts'].subject.subject_type == 'TUTORIAL')
    # ── Workload breakdown — Contact Hours ───────────────────────────────────
    # 1 slot = 1 contact hour (standard academic convention)
    # Theory / NPTEL / Tutorial = 1 slot = 1 contact hr per session
    # Lab = 2 slots = 2 contact hrs per session
    theory_contact  = total_theory   * 1
    lab_contact     = total_lab      * 2   # lab covers 2 slots = 2 contact hrs
    tutorial_contact= total_tutorial * 1
    total_contact   = theory_contact + lab_contact + tutorial_contact

    def fmt_contact(hrs):
        if hrs == 0:
            return '0 hrs'
        return f'{hrs} hrs'

    workload = {
        'theory_mins':       theory_contact,
        'lab_mins':          lab_contact,
        'tutorial_mins':     tutorial_contact,
        'total_mins':        total_contact,
        'theory_fmt':        fmt_contact(theory_contact),
        'lab_fmt':           fmt_contact(lab_contact),
        'tutorial_fmt':      fmt_contact(tutorial_contact),
        'total_fmt':         fmt_contact(total_contact),
        'lab_per_session':   '2 hrs',    # 1 lab = 2 contact hrs
        'total_sessions':    total_theory + total_lab + total_tutorial,
    }

    import base64
    prof_url = request.build_absolute_uri(f'/professor/{professor_id}/')
    qr_b64 = base64.b64encode(_make_qr_png(prof_url, professor.name).read()).decode()
    return render(request, 'professor_schedule.html', {
        'professor': professor,
        'table': table,
        'days': DAYS,
        'slots': SLOTS,
        'slot_times': SLOT_TIMES,
        'total_slots': total_slots,
        'total_theory': total_theory,
        'total_lab': total_lab,
        'total_tutorial': total_tutorial,
        'workload': workload,
        'qr_b64': qr_b64,
        'qr_url': prof_url,
        'occupied_times': occupied_times,
        'occupied_map': occupied_map,
        'slot_times_display': SLOT_TIMES_DISPLAY,
        'lunch_label': '12:20–1:10',
    })


# ─── Year / Section Timetable Views ──────────────────────────────────────────

# Slot END times (what appears after the dash in the header label)
SLOT_END_TIMES = {
    1: "9:50",  2: "10:40", 3: "11:30",
    4: "12:20", 5: "1:10",  6: "2:50",  7: "3:40", 8: "4:30",
}

def _get_lunch_label(dept_id):
    """The 1:10–2:00 gap is the fixed break column — always shown as-is."""
    return "1:10–2:00"


def _get_lunch_slots(dept_id):
    """Return the set of slot numbers marked as lunch for this dept."""
    try:
        ds = DepartmentSettings.objects.get(department_id=dept_id)
        return set(ds.get_lunch_slots())
    except DepartmentSettings.DoesNotExist:
        return set()


def _get_dept_start_slot(dept_id):
    try:
        ds = DepartmentSettings.objects.get(department_id=dept_id)
        return ds.get_start_slot()
    except DepartmentSettings.DoesNotExist:
        return 1


def year_timetable(request, course_id, year):
    course = get_object_or_404(Course, id=course_id)
    sections = Section.objects.filter(course=course, year=year).select_related('course__department')
    if not sections.exists():
        messages.error(request, 'No sections found for this year.')
        return redirect('dashboard')
    section_tables = []
    for section in sections:
        table = {}
        for day in DAYS:
            cells = []
            skip_next = False
            for i, slot in enumerate(SLOTS):
                if skip_next:
                    skip_next = False
                    cells.append({'entry': None, 'colspan': 1, 'skip': True, 'slot': slot})
                    continue
                entry = TimeSlot.objects.filter(day=day, slot=slot, section=section).select_related('subject', 'professor', 'room').first()
                if entry and entry.subject.subject_type == 'LAB':
                    next_slot = SLOTS[i + 1] if i + 1 < len(SLOTS) else None
                    if next_slot:
                        next_entry = TimeSlot.objects.filter(day=day, slot=next_slot, section=section).first()
                        if next_entry and next_entry.subject == entry.subject:
                            cells.append({'entry': entry, 'colspan': 2, 'skip': False, 'slot': slot})
                            skip_next = True
                            continue
                cells.append({'entry': entry, 'colspan': 1, 'skip': False, 'slot': slot})
            table[day] = cells
        section_tables.append({'section': section, 'table': table})
    year_display = dict(Section.YEAR_CHOICES).get(year, year)
    dept_id = course.department_id
    lunch_label = _get_lunch_label(dept_id)
    lunch_slots = _get_lunch_slots(dept_id)
    return render(request, 'year_timetable.html', {
        'course': course, 'year': year, 'year_display': year_display,
        'section_tables': section_tables, 'slots': SLOTS, 'slot_times': SLOT_TIMES,
        'days': DAYS, 'lunch_label': lunch_label, 'lunch_slots': lunch_slots,
    })


def section_timetable(request, section_id):
    section = get_object_or_404(Section, id=section_id)
    table = {}
    for day in DAYS:
        cells = []
        skip_next = False
        for i, slot in enumerate(SLOTS):
            if skip_next:
                skip_next = False
                cells.append({'entry': None, 'colspan': 1, 'skip': True, 'slot': slot})
                continue
            entry = TimeSlot.objects.filter(day=day, slot=slot, section=section).select_related('subject', 'professor', 'room').first()
            if entry and entry.subject.subject_type == 'LAB':
                next_slot = SLOTS[i + 1] if i + 1 < len(SLOTS) else None
                if next_slot:
                    next_entry = TimeSlot.objects.filter(day=day, slot=next_slot, section=section).first()
                    if next_entry and next_entry.subject == entry.subject:
                        cells.append({'entry': entry, 'colspan': 2, 'skip': False, 'slot': slot})
                        skip_next = True
                        continue
            cells.append({'entry': entry, 'colspan': 1, 'skip': False, 'slot': slot})
        table[day] = cells
    import base64
    qr_url = request.build_absolute_uri(f'/timetable/{section_id}/')
    qr_b64 = base64.b64encode(_make_qr_png(qr_url, str(section)).read()).decode()
    lunch_label = _get_lunch_label(section.course.department_id)
    lunch_slots = _get_lunch_slots(section.course.department_id)
    return render(request, 'timetable.html', {
        'table': table, 'slots': SLOTS, 'slot_times': SLOT_TIMES,
        'section': section, 'qr_b64': qr_b64, 'qr_url': qr_url,
        'lunch_label': lunch_label, 'lunch_slots': lunch_slots,
    })


def section_combined_timetable(request, course_id, year, section_name):
    course = get_object_or_404(Course, id=course_id)
    groups = Section.objects.filter(course=course, year=year, section_name=section_name).select_related('course__department').order_by('group')
    if not groups.exists():
        messages.error(request, 'No groups found for this section.')
        return redirect('dashboard')
    group_tables = []
    for section in groups:
        table = {}
        for day in DAYS:
            cells = []
            skip_next = False
            for i, slot in enumerate(SLOTS):
                if skip_next:
                    skip_next = False
                    cells.append({'entry': None, 'colspan': 1, 'skip': True, 'slot': slot})
                    continue
                entry = TimeSlot.objects.filter(day=day, slot=slot, section=section).select_related('subject', 'professor', 'room').first()
                if entry and entry.subject.subject_type == 'LAB':
                    next_slot = SLOTS[i + 1] if i + 1 < len(SLOTS) else None
                    if next_slot:
                        next_entry = TimeSlot.objects.filter(day=day, slot=next_slot, section=section).first()
                        if next_entry and next_entry.subject == entry.subject:
                            cells.append({'entry': entry, 'colspan': 2, 'skip': False, 'slot': slot})
                            skip_next = True
                            continue
                cells.append({'entry': entry, 'colspan': 1, 'skip': False, 'slot': slot})
            table[day] = cells
        group_tables.append({'section': section, 'table': table})
    year_display = dict(Section.YEAR_CHOICES).get(year, year)
    lunch_label = _get_lunch_label(course.department_id)
    lunch_slots = _get_lunch_slots(course.department_id)
    return render(request, 'section_combined_timetable.html', {
        'course': course, 'year': year, 'year_display': year_display,
        'section_name': section_name, 'group_tables': group_tables,
        'slots': SLOTS, 'slot_times': SLOT_TIMES, 'days': DAYS,
        'lunch_label': lunch_label, 'lunch_slots': lunch_slots,
    })


# ─── Generate Timetable ──────────────────────────────────────────────────────

def generate_timetable(request):
    TimeSlot.objects.all().delete()
    all_sections = list(Section.objects.prefetch_related('subjects__professors').select_related('course__department').all())
    if not all_sections:
        messages.error(request, '❌ No sections found.')
        return redirect('dashboard')

    all_rooms = list(Room.objects.select_related('department').all())
    all_classrooms = [r for r in all_rooms if r.room_type == 'CLASSROOM']
    all_labs = [r for r in all_rooms if r.room_type == 'LAB']

    def get_dept_rooms(room_list, dept_id):
        assigned = [r for r in room_list if r.department_id == dept_id]
        shared   = [r for r in room_list if r.department_id is None]
        others   = [r for r in room_list if r.department_id is not None and r.department_id != dept_id]
        return assigned + shared + others

    room_busy = {}
    def get_free_room(room_list, day, slot, slots_needed=1, subject_name='', subject_code='', min_capacity=0):
        # 2-tier priority: preferred (subject match / unrestricted) first, fallback second
        # min_capacity: if set, only rooms with capacity >= min_capacity are considered
        preferred, fallback = [], []
        for room in room_list:
            if not all((room.id, day, slot + i) not in room_busy for i in range(slots_needed)):
                continue
            if min_capacity and room.capacity < min_capacity:
                continue  # room too small for this section
            if room.room_type == 'LAB' and (subject_name or subject_code):
                if room.can_host_subject(subject_name, subject_code):
                    preferred.append(room)
                else:
                    fallback.append(room)
            else:
                preferred.append(room)
        candidates = preferred if preferred else fallback
        # Among candidates, prefer smallest sufficient room (less wastage)
        if candidates and min_capacity:
            candidates.sort(key=lambda r: r.capacity)
        return candidates[0] if candidates else None
    def mark_room_busy(room, day, slot, slots_needed=1):
        for i in range(slots_needed):
            room_busy[(room.id, day, slot + i)] = True

    professor_busy = {}
    def is_prof_free(prof_id, day, slot):
        return (day, slot) not in professor_busy.get(prof_id, {})
    def mark_prof_busy(prof_id, day, slot):
        professor_busy.setdefault(prof_id, {})[(day, slot)] = True

    # ── Pre-block professor occupied times ────────────────────────────────────
    prof_block_details = {}  # prof_id → [(day, slot, reason)]
    for occ in ProfessorOccupiedTime.objects.all():
        for slot in occ.blocked_slots():
            mark_prof_busy(occ.professor_id, occ.day, slot)
            prof_block_details.setdefault(occ.professor_id, []).append(
                (occ.day, slot, occ.get_activity_type_display()))

    # ── Pre-block room/lab occupied times ────────────────────────────────────
    room_block_details = {}  # room_id → [(day, slot, reason)]
    for rocc in RoomOccupiedTime.objects.all():
        for slot in rocc.blocked_slots():
            mark_room_busy(rocc.room, rocc.day, slot)
            room_block_details.setdefault(rocc.room_id, []).append(
                (rocc.day, slot, rocc.get_purpose_display()))

    total_created = 0
    skipped = []
    clash_warnings = []
    no_room_warn = []

    pair_map = defaultdict(list)
    for sec in all_sections:
        pair_map[(sec.course_id, sec.year, sec.section_name)].append(sec)

    for pair_key, sections_in_pair in pair_map.items():
        dept_id = sections_in_pair[0].course.department_id
        dept_classrooms = get_dept_rooms(all_classrooms, dept_id)
        dept_labs        = get_dept_rooms(all_labs, dept_id)

        # ── Dept settings: respect lunch slots and start time ─────────────────
        try:
            ds = DepartmentSettings.objects.get(department_id=dept_id)
            lunch_slots_dept = ds.get_lunch_slots()
            dept_start = ds.get_start_slot()
        except DepartmentSettings.DoesNotExist:
            lunch_slots_dept = []
            dept_start = 1
        avail_slots_dept = [s for s in SLOTS if s not in lunch_slots_dept and s >= dept_start]
        # section_start_slot override
        sec_starts_old = [sec.section_start_slot for sec in sections_in_pair if sec.section_start_slot]
        if sec_starts_old:
            eff_start_old = min(sec_starts_old)
            avail_slots_dept = [s for s in SLOTS if s not in lunch_slots_dept and s >= eff_start_old]
        avail_nptel_slots = [s for s in NPTEL_SLOTS if s not in lunch_slots_dept and s >= (min(sec_starts_old) if sec_starts_old else dept_start)]

        theory_subjects = {}
        nptel_subjects = {}           # grouped by subject name — same logic as THEORY
        lab_subjects_by_section = defaultdict(list)
        tutorial_subjects_by_section = defaultdict(list)

        for sec in sections_in_pair:
            for subj in sec.subjects.all():
                if not subj.professors.exists():
                    continue
                if subj.subject_type == 'THEORY':
                    if subj.name not in theory_subjects:
                        theory_subjects[subj.name] = {'subj': subj, 'sections': [sec], 'subj_per_sec': {sec.id: subj}}
                    else:
                        theory_subjects[subj.name]['sections'].append(sec)
                        theory_subjects[subj.name]['subj_per_sec'][sec.id] = subj
                elif subj.subject_type == 'LAB':
                    lab_subjects_by_section[sec.id].append(subj)
                elif subj.subject_type == 'TUTORIAL':
                    tutorial_subjects_by_section[sec.id].append(subj)
                elif subj.subject_type == 'NPTEL':
                    # Group both sections under the same subject name (mirrors THEORY logic)
                    if subj.name not in nptel_subjects:
                        nptel_subjects[subj.name] = {'subj': subj, 'sections': [sec], 'subj_per_sec': {sec.id: subj}}
                    else:
                        nptel_subjects[subj.name]['sections'].append(sec)
                        nptel_subjects[subj.name]['subj_per_sec'][sec.id] = subj

        if (not theory_subjects and not any(lab_subjects_by_section.values())
                and not any(tutorial_subjects_by_section.values())
                and not nptel_subjects):
            for sec in sections_in_pair:
                skipped.append(str(sec))
            continue

        # ── Theory scheduling ────────────────────────────────────────────────
        theory_list = list(theory_subjects.values())
        theory_pool = []
        for t in theory_list:
            for _ in range(t['subj'].lectures_per_week):
                theory_pool.append(t)
        # No shuffle — deterministic slot filling
        PRE_LUNCH_CAP_OLD = len([s for s in avail_slots_dept if s < lunch_start_old])
        theory_day_assignments = defaultdict(list)
        for t in theory_pool:
            candidate_days = [d for d in DAYS if t not in theory_day_assignments[d]]
            if not candidate_days:
                candidate_days = DAYS[:]
            under_cap = [d for d in candidate_days if len(theory_day_assignments[d]) < PRE_LUNCH_CAP_OLD]
            pool = under_cap if under_cap else candidate_days
            chosen_day = max(pool, key=lambda d: len(theory_day_assignments[d]))
            theory_day_assignments[chosen_day].append(t)

        # ── Free-day constraint per section (old scheduler) ──────────────────
        pair_free_days_old = set(sec.free_day for sec in sections_in_pair if sec.free_day)
        effective_days_old = [d for d in DAYS if d not in pair_free_days_old] or DAYS[:]
        lunch_start_old = min(lunch_slots_dept) if lunch_slots_dept else (dept_start + 4)

        theory_day_assignments = defaultdict(list)
        for t in theory_pool:
            candidate_days = [d for d in effective_days_old if t not in theory_day_assignments[d]]
            if not candidate_days:
                candidate_days = effective_days_old[:]
            chosen_day = min(candidate_days, key=lambda d: len(theory_day_assignments[d]))
            theory_day_assignments[chosen_day].append(t)

        for day in DAYS:
            for t in theory_day_assignments[day]:
                subj = t['subj']
                professor = subj.professors.first()
                prof_id = professor.id
                free_slots = sorted(
                    [s for s in avail_slots_dept if s not in pair_used_slots[day] and is_prof_free(prof_id, day, s)]
                )
                if not free_slots:
                    clash_warnings.append(f"{subj.name} (Sec {pair_key[2]}) on {day} — no free slot")
                    continue

                # Try each free slot until we find one with a free room
                chosen_slot, cls_room = None, None
                for sl in free_slots:
                    r = get_free_room(dept_classrooms, day, sl)
                    if r:
                        chosen_slot, cls_room = sl, r
                        break
                if chosen_slot is None:
                    no_room_warn.append(f"No classroom for {subj.name} on {day}")
                    continue

                for sec in t['sections']:
                    sec_subj = t['subj_per_sec'].get(sec.id, subj)
                    TimeSlot.objects.create(day=day, slot=chosen_slot, subject=sec_subj,
                                            professor=professor, section=sec, room=cls_room)
                    total_created += 1
                pair_used_slots[day].add(chosen_slot)
                mark_prof_busy(prof_id, day, chosen_slot)
                mark_room_busy(cls_room, day, chosen_slot)

        # ── NPTEL scheduling (slot 6 first, then 7,8,9 — all post-lunch) ──────
        # Both groups get the same professor, room, and time slot (mirrors THEORY logic).
        nptel_list = list(nptel_subjects.values())
        nptel_pool = []
        for n in nptel_list:
            for _ in range(n['subj'].lectures_per_week):
                nptel_pool.append(n)
        random.shuffle(nptel_pool)

        for n in nptel_pool:
            nsubj = n['subj']
            professor = nsubj.professors.first()
            prof_id = professor.id
            candidates = []
            for day in effective_days_old:
                for s in avail_nptel_slots:  # ← Enforce after-2PM + lunch/start-time constraint
                    if s not in pair_used_slots[day] and is_prof_free(prof_id, day, s):
                        candidates.append((day, s))
            candidates.sort(key=lambda x: x[1])  # lowest slot first
            placed = False
            for day, s in candidates:
                if s in pair_used_slots[day] or not is_prof_free(prof_id, day, s):
                    continue
                cls_room = get_free_room(dept_classrooms, day, s)
                # Assign the same slot, professor, and room to ALL sections in the group
                for sec in n['sections']:
                    sec_subj = n['subj_per_sec'].get(sec.id, nsubj)
                    TimeSlot.objects.create(day=day, slot=s, subject=sec_subj,
                                            professor=professor, section=sec, room=cls_room)
                    total_created += 1
                pair_used_slots[day].add(s)
                mark_prof_busy(prof_id, day, s)
                if cls_room:
                    mark_room_busy(cls_room, day, s)
                else:
                    no_room_warn.append(f"No room for NPTEL {nsubj.name}")
                placed = True
                break
            if not placed:
                clash_warnings.append(
                    f"NPTEL {nsubj.name} — no after-2PM slot available "
                    f"(only after-2PM slots allowed; professor {professor.name} may be busy)"
                )

        # ── Lab scheduling ────────────────────────────────────────────────────
        for sec in sections_in_pair:
            lab_subjs = lab_subjects_by_section.get(sec.id, [])
            if not lab_subjs:
                continue
            lab_pool = []
            for ls in lab_subjs:
                for _ in range(ls.lectures_per_week):
                    lab_pool.append(ls)
            random.shuffle(lab_pool)
            sec_lab_days_used: set = set()
            is_g1 = sec.group == 'G1'
            preferred_starts = GROUP_ONE_LAB_STARTS if is_g1 else GROUP_TWO_LAB_STARTS

            for ls in lab_pool:
                professor = ls.professors.first()
                prof_id = professor.id
                # Pinned lab room support
                pinned_room = ls.lab_room
                candidates = []
                for day in DAYS:
                    sec_used_day = set(pair_used_slots[day])
                    for ts_obj in TimeSlot.objects.filter(section=sec, day=day):
                        sec_used_day.add(ts_obj.slot)
                    if day in sec_lab_days_used:
                        continue
                    # Skip section's free/holiday day
                    if sec.free_day and day == sec.free_day:
                        continue
                    valid_pairs = [
                        (s, s + 1) for s in avail_slots_dept
                        if s + 1 in avail_slots_dept
                        and s not in sec_used_day
                        and s + 1 not in sec_used_day
                        and s not in LAB_FORBIDDEN_START
                        and is_prof_free(prof_id, day, s)
                        and is_prof_free(prof_id, day, s + 1)
                        # Check pinned room available if specified
                        and (pinned_room is None
                             or ((pinned_room.id, day, s) not in room_busy
                                 and (pinned_room.id, day, s + 1) not in room_busy))
                    ]
                    for s1, s2 in valid_pairs:
                        priority = 0 if s1 in preferred_starts else 1
                        candidates.append((priority, day, s1, s2))
                # Sort: priority first, then slot asc across full day
                candidates.sort(key=lambda x: (x[0], x[2]))

                placed = False
                for priority, day, s1, s2 in candidates:
                    sec_used_day = set(pair_used_slots[day])
                    for ts_obj in TimeSlot.objects.filter(section=sec, day=day):
                        sec_used_day.add(ts_obj.slot)
                    if s1 in sec_used_day or s2 in sec_used_day:
                        continue
                    if not is_prof_free(prof_id, day, s1) or not is_prof_free(prof_id, day, s2):
                        continue

                    # Use pinned room if set; else auto-find
                    if pinned_room:
                        if ((pinned_room.id, day, s1) in room_busy
                                or (pinned_room.id, day, s2) in room_busy):
                            continue
                        lab_room = pinned_room
                    else:
                        lab_room = get_free_room(dept_labs, day, s1, slots_needed=2,
                                                  subject_name=ls.name, subject_code=ls.subject_code)

                    TimeSlot.objects.create(day=day, slot=s1, subject=ls,
                                            professor=professor, section=sec, room=lab_room)
                    TimeSlot.objects.create(day=day, slot=s2, subject=ls,
                                            professor=professor, section=sec, room=lab_room)
                    mark_prof_busy(prof_id, day, s1)
                    mark_prof_busy(prof_id, day, s2)
                    sec_lab_days_used.add(day)
                    if lab_room:
                        mark_room_busy(lab_room, day, s1, slots_needed=2)
                    else:
                        no_room_warn.append(f"No lab room for {ls.name} ({sec})")
                    total_created += 2
                    placed = True
                    break

                if not placed:
                    clash_warnings.append(
                        f"{ls.name} ({sec}) — no available lab slot "
                        f"(professor {professor.name} fully booked or pinned room occupied)"
                    )

        # ── Tutorial scheduling ───────────────────────────────────────────────
        for sec in sections_in_pair:
            tut_subjs = tutorial_subjects_by_section.get(sec.id, [])
            if not tut_subjs:
                continue
            tut_pool = []
            for ts in tut_subjs:
                for _ in range(ts.lectures_per_week):
                    tut_pool.append(ts)
            random.shuffle(tut_pool)
            sec_tut_days_used: set = set()

            for tsubj in tut_pool:
                professor = tsubj.professors.first()
                prof_id = professor.id
                candidates = []
                for day in DAYS:
                    if day in sec_tut_days_used:
                        continue
                    # Skip section's free/holiday day
                    if sec.free_day and day == sec.free_day:
                        continue
                    sec_used_day = set(pair_used_slots[day])
                    for ts_obj in TimeSlot.objects.filter(section=sec, day=day):
                        sec_used_day.add(ts_obj.slot)
                    for s in avail_slots_dept:
                        if s not in sec_used_day and is_prof_free(prof_id, day, s):
                            candidates.append((day, s))
                candidates.sort(key=lambda x: x[1])

                placed = False
                for day, s in candidates:
                    sec_used_day = set(pair_used_slots[day])
                    for ts_obj in TimeSlot.objects.filter(section=sec, day=day):
                        sec_used_day.add(ts_obj.slot)
                    if s in sec_used_day or not is_prof_free(prof_id, day, s):
                        continue
                    cls_room = get_free_room(dept_classrooms, day, s)
                    TimeSlot.objects.create(day=day, slot=s, subject=tsubj,
                                            professor=professor, section=sec, room=cls_room)
                    mark_prof_busy(prof_id, day, s)
                    sec_tut_days_used.add(day)
                    if cls_room:
                        mark_room_busy(cls_room, day, s)
                    else:
                        no_room_warn.append(f"No room for tutorial {tsubj.name} ({sec})")
                    total_created += 1
                    placed = True
                    break

                if not placed:
                    clash_warnings.append(
                        f"{tsubj.name} tutorial ({sec}) — no available slot across the week"
                    )

    if total_created > 0:
        messages.success(request, f'✅ Timetable generated! {total_created} slots created.')
    else:
        messages.error(request, '❌ No timetable generated.')
    if skipped:
        messages.warning(request, f'⚠️ Skipped (no subjects): {", ".join(skipped[:3])}{"..." if len(skipped)>3 else ""}')
    if clash_warnings:
        messages.warning(request, f'⚠️ Conflicts ({len(clash_warnings)}): {"; ".join(clash_warnings[:3])}{"..." if len(clash_warnings) > 3 else ""}')
    if no_room_warn:
        unique = list(dict.fromkeys(no_room_warn))
        messages.warning(request, f'⚠️ Room shortage ({len(unique)} cases): {"; ".join(unique[:2])}{"..." if len(unique) > 2 else ""}')

    # ── G1 / G2 Professor Sync Pass (old generator) ─────────────────────────────
    # THEORY subjects: G1 and G2 attend the same physical lecture → same professor.
    # LAB / TUTORIAL subjects: separate sessions → keep their own professor.
    for pair_key, sections_in_pair in pair_map.items():
        g1_secs = [s for s in sections_in_pair if s.group == 'G1']
        g2_secs = [s for s in sections_in_pair if s.group == 'G2']
        if not g1_secs or not g2_secs:
            continue
        g1_prof_map = {}
        for ts_obj in TimeSlot.objects.filter(section=g1_secs[0]).select_related('subject'):
            # Only sync THEORY and NPTEL — lab/tutorial are independent sessions
            if ts_obj.subject.subject_type in ('THEORY', 'NPTEL'):
                g1_prof_map[ts_obj.subject.name] = ts_obj.professor_id
        for ts_obj in TimeSlot.objects.filter(section=g2_secs[0]).select_related('subject'):
            if ts_obj.subject.subject_type not in ('THEORY', 'NPTEL'):
                continue
            matched = g1_prof_map.get(ts_obj.subject.name)
            if matched and ts_obj.professor_id != matched:
                ts_obj.professor_id = matched
                ts_obj.save()

    # ── Sync Subject.professors M2M → match actual TimeSlot.professor ─────────
    # The workload report reads Subject.professors (set during CSV import).
    # After generation, timeslots may have a different professor (e.g. shared
    # G1/G2 theory slot picks G1's professor for G2 as well).
    # Syncing here ensures workload report matches the individual schedules.
    for ts_obj in TimeSlot.objects.select_related('subject', 'professor').all():
        if ts_obj.professor and ts_obj.subject:
            ts_obj.subject.professors.set([ts_obj.professor])

    # ── Workload balance report ───────────────────────────────────────────────
    prof_loads = {}
    for ts in TimeSlot.objects.select_related('professor', 'subject'):
        pid = ts.professor_id
        prof_loads.setdefault(pid, {'name': ts.professor.name, 'slots': 0, 'hours': 0})
        prof_loads[pid]['slots'] += 1
        prof_loads[pid]['hours'] += 100 if ts.subject.subject_type == 'LAB' else 50

    if prof_loads:
        hours = [v['hours'] for v in prof_loads.values()]
        max_h = max(hours); min_h = min(hours); avg_h = sum(hours) // len(hours)
        overloaded = [v['name'] for v in prof_loads.values() if v['hours'] > avg_h * 1.4]
        underloaded = [v['name'] for v in prof_loads.values() if v['hours'] < avg_h * 0.6]
        if overloaded:
            messages.info(request, f'📊 Workload: avg {avg_h//60}h{avg_h%60}m/week. '
                          f'Overloaded: {", ".join(overloaded[:3])}')
        if underloaded:
            messages.info(request, f'📊 Underutilised professors: {", ".join(underloaded[:3])}')

    # ── Lab utilisation report ────────────────────────────────────────────────
    from collections import Counter
    lab_usage = Counter()
    for ts in TimeSlot.objects.filter(subject__subject_type='LAB').select_related('room'):
        if ts.room:
            lab_usage[ts.room.name] += 1
    if lab_usage:
        total_lab_slots = len(DAYS) * len(SLOTS)
        poorly_used = [f"{nm}({cnt} slots)" for nm, cnt in lab_usage.items() if cnt <= 2]
        if poorly_used:
            messages.info(request, f'🧪 Low lab usage: {", ".join(poorly_used[:3])}')

    return redirect('dashboard')


# ─── PDF / QR Exports (unchanged) ────────────────────────────────────────────

def _get_pdf_styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    return {
        'cell':          ParagraphStyle('c',  fontSize=7,   fontName='Helvetica-Bold', alignment=TA_CENTER, leading=9,  textColor=colors.HexColor('#1e3a5f')),
        'prof':          ParagraphStyle('p',  fontSize=5.5, fontName='Helvetica',      alignment=TA_CENTER, leading=7,  textColor=colors.HexColor('#475569')),
        'head':          ParagraphStyle('h',  fontSize=7,   fontName='Helvetica-Bold', alignment=TA_CENTER, leading=9,  textColor=colors.white),
        'day':           ParagraphStyle('d',  fontSize=8,   fontName='Helvetica-Bold', alignment=TA_CENTER,             textColor=colors.HexColor('#1e3a5f')),
        'title':         ParagraphStyle('t',  fontSize=14,  fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=3, textColor=colors.HexColor('#1e3a5f')),
        'sub':           ParagraphStyle('s',  fontSize=8,   fontName='Helvetica',      alignment=TA_CENTER, spaceAfter=10, textColor=colors.HexColor('#64748b')),
        'section_title': ParagraphStyle('st', fontSize=11,  fontName='Helvetica-Bold', alignment=TA_CENTER, spaceAfter=3, textColor=colors.HexColor('#1e3a5f')),
        'type_tag':      ParagraphStyle('tt', fontSize=5,   fontName='Helvetica-Bold', alignment=TA_CENTER, leading=6,  textColor=colors.HexColor('#6b7280')),
    }


def _pdf_slot_to_col(slot):
    """Map slot number (1-9) to table column index (0=Day, 6=Lunch)."""
    return slot if slot <= 5 else slot + 1


def _build_pdf_table(data, label, styles_map):
    """Beautiful section timetable table with lab colspan.
    data[day][slot] = single TimeSlot object or None.
    """
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    BLUE      = colors.HexColor('#1565c0')
    NAVY      = colors.HexColor('#1e3a5f')
    THEORY_BG = colors.HexColor('#EFF6FF'); THEORY_BD = colors.HexColor('#BFDBFE')
    LAB_BG    = colors.HexColor('#F0FDF4'); LAB_BD    = colors.HexColor('#86EFAC')
    TUT_BG    = colors.HexColor('#FDF4FF'); TUT_BD    = colors.HexColor('#E9D5FF')
    NPTEL_BG  = colors.HexColor('#FEF3C7')
    LUNCH_BG  = colors.HexColor('#FFF7ED')
    DAY_BG    = colors.HexColor('#F1F5F9')
    EMPTY_COL = colors.HexColor('#F8FAFC')
    GRID_COL  = colors.HexColor('#E2E8F0')

    TYPE_LABEL = {'LAB':'🔬 LAB','TUTORIAL':'📘 TUT','NPTEL':'📡 NPTEL','THEORY':'📖 THEORY'}

    def _bg(st):
        return LAB_BG if st=='LAB' else TUT_BG if st=='TUTORIAL' else NPTEL_BG if st=='NPTEL' else THEORY_BG

    slot_labels = (["Day"] + [SLOT_TIMES[s] for s in SLOTS[:5]] +
                   ["Lunch\n1:10–2:00"] + [SLOT_TIMES[s] for s in SLOTS[5:]])
    header_row = [Paragraph(s.replace('\n','<br/>'), styles_map['head']) for s in slot_labels]
    rows = [header_row]
    bg_cmds   = [('BACKGROUND',(0,0),(-1,0),BLUE),
                 ('BACKGROUND',(6,1),(6,len(DAYS)),LUNCH_BG),
                 ('BACKGROUND',(0,1),(0,-1),DAY_BG)]
    span_cmds = []

    for ri, day in enumerate(DAYS, start=1):
        row = [Paragraph(f"<b>{day[:3]}</b>", styles_map['day'])]
        skip_next = False
        for slot in SLOTS:
            if slot == 6:
                row.append(Paragraph("🍽<br/><b>Lunch</b>", styles_map['prof']))
            if skip_next:
                skip_next = False
                continue
            ci   = _pdf_slot_to_col(slot)
            ts   = data[day][slot]
            # Lab colspan check
            next_slot = slot + 1 if slot < 9 else None
            next_ts   = data[day][next_slot] if next_slot and next_slot != 6 else None
            is_lab_span = (ts and next_ts and
                           ts.subject.subject_type == 'LAB' and
                           next_ts.subject.subject_type == 'LAB' and
                           ts.subject_id == next_ts.subject_id and
                           ts.section_id == next_ts.section_id and
                           slot != 5)
            if ts:
                st = ts.subject.subject_type
                bg = _bg(st)
                content = []
                if ts.subject.code:
                    content.append(Paragraph(f"<b>{ts.subject.code}</b>", styles_map['prof']))
                content.append(Paragraph(f"<b>{ts.subject.name}</b>", styles_map['cell']))
                content.append(Paragraph(ts.professor.name, styles_map['prof']))
                if ts.room:
                    content.append(Paragraph(f"🚪 {ts.room.name}", styles_map['prof']))
                content.append(Paragraph(TYPE_LABEL.get(st, st), styles_map['type_tag']))
                row.append(content)
                bg_cmds.append(('BACKGROUND',(ci,ri),(ci,ri),bg))
                if is_lab_span:
                    ci_next = _pdf_slot_to_col(next_slot)
                    span_cmds.append(('SPAN',(ci,ri),(ci_next,ri)))
                    skip_next = True
            else:
                row.append(Paragraph("—", styles_map['prof']))
                bg_cmds.append(('BACKGROUND',(ci,ri),(ci,ri),EMPTY_COL))
        rows.append(row)

    col_widths  = [1.7*cm] + [2.6*cm]*5 + [1.8*cm] + [2.6*cm]*4
    row_heights = [1.0*cm] + [2.2*cm]*len(DAYS)
    t = Table(rows, colWidths=col_widths, rowHeights=row_heights)
    t.setStyle(TableStyle([
        ('GRID',          (0,0),(-1,-1), 0.5, GRID_COL),
        ('BOX',           (0,0),(-1,-1), 1.2, BLUE),
        ('LINEBEFORE',    (6,0),(6,-1),  1.0, colors.HexColor('#fed7aa')),
        ('LINEAFTER',     (6,0),(6,-1),  1.0, colors.HexColor('#fed7aa')),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('ALIGN',         (0,0),(-1,-1), 'CENTER'),
        ('TOPPADDING',    (0,0),(-1,-1), 4),
        ('BOTTOMPADDING', (0,0),(-1,-1), 4),
        ('LEFTPADDING',   (0,0),(-1,-1), 3),
        ('RIGHTPADDING',  (0,0),(-1,-1), 3),
        ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#FAFBFF')]),
        ('FONTNAME',      (0,0),(-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0),(-1,0),  7),
        ('TEXTCOLOR',     (0,0),(-1,0),  colors.white),
    ] + bg_cmds + span_cmds))
    return t


def export_pdf(request, section_id):
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, HRFlowable
    section = get_object_or_404(Section, id=section_id)
    data = _build_tt_data(section)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=1.2*cm, rightMargin=1.2*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles_map = _get_pdf_styles()
    year_display = section.get_year_display_label()
    label = (f"{section.course.department.name} — {section.course.get_display_name()} — "
             f"{year_display} — Sec {section.get_effective_section_name()} — {section.get_group_display()}")
    elements = [
        Paragraph(label, styles_map['title']),
        Paragraph("Auto-generated Weekly Timetable", styles_map['sub']),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor('#1565c0'), spaceAfter=8),
        _build_pdf_table(data, label, styles_map),
    ]
    doc.build(elements)
    buffer.seek(0)
    fname = f"timetable_{section.course.department.name}_{section.year}_{section.group}.pdf".replace(' ', '_')
    resp = HttpResponse(buffer, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


def export_year_pdf(request, course_id, year):
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak
    course = get_object_or_404(Course, id=course_id)
    sections = Section.objects.filter(course=course, year=year)
    year_display = dict(Section.YEAR_CHOICES).get(year, year)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1*cm, rightMargin=1*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles_map = _get_pdf_styles()
    elements = []
    for i, section in enumerate(sections):
        if i > 0:
            elements.append(PageBreak())
        label = f"{course.department.name} — {course.get_display_name()} — {year_display} — {section.group}"
        data = _build_tt_data(section)
        elements += [Paragraph(label, styles_map['title']), Paragraph("Auto-generated Weekly Timetable", styles_map['sub']), _build_pdf_table(data, label, styles_map)]
    doc.build(elements)
    buffer.seek(0)
    fname = f"timetable_{course.department.name}_{year_display}_all.pdf".replace(' ', '_')
    resp = HttpResponse(buffer, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


def export_section_combined_pdf(request, course_id, year, section_name):
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    course = get_object_or_404(Course, id=course_id)
    groups = list(Section.objects.filter(course=course, year=year, section_name=section_name).order_by('group'))
    year_display = dict(Section.YEAR_CHOICES).get(year, year)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1*cm, rightMargin=1*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles_map = _get_pdf_styles()
    BLUE = colors.HexColor('#1a56db')
    elements = [Paragraph(f"{course.department.name} — {course.get_display_name()} — {year_display} — Section {section_name} Combined", styles_map['title']),
                Paragraph("Auto-generated Combined Weekly Timetable", styles_map['sub'])]
    for i, section in enumerate(groups):
        label = f"Group {section.group}"
        data = _build_tt_data(section)
        elements += [Paragraph(label, styles_map['section_title']), _build_pdf_table(data, label, styles_map), Spacer(1, 0.3*cm)]
    if not groups:
        elements = [Paragraph("No timetable data found.", styles_map['sub'])]
    doc.build(elements)
    buffer.seek(0)
    fname = f"section_{section_name}_{year_display}_{course.department.name}_combined.pdf".replace(' ', '_')
    resp = HttpResponse(buffer, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


def _build_combined_pdf_table(g1_data, g2_data, styles_map):
    """Build a combined timetable table - compact layout so G1+G2 fit cleanly in each cell."""
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    # Compact styles with tight leading so dual entries fit without overflow
    s_name = ParagraphStyle('cn', fontSize=5.5, fontName='Helvetica-Bold',
                             alignment=TA_CENTER, leading=7, spaceAfter=0, spaceBefore=0)
    s_info = ParagraphStyle('ci', fontSize=5, fontName='Helvetica',
                             alignment=TA_CENTER, leading=6, spaceAfter=0, spaceBefore=0,
                             textColor=colors.HexColor('#555555'))
    s_div  = ParagraphStyle('cd', fontSize=3.5, fontName='Helvetica',
                             alignment=TA_CENTER, leading=5, spaceAfter=0, spaceBefore=0,
                             textColor=colors.HexColor('#bbbbbb'))
    s_dash = ParagraphStyle('cdd', fontSize=6, fontName='Helvetica',
                             alignment=TA_CENTER, leading=7, spaceAfter=0, spaceBefore=0,
                             textColor=colors.HexColor('#aaaaaa'))

    BLUE       = colors.HexColor('#1a56db')
    THEORY_BG  = colors.HexColor('#eff6ff')
    LAB_BG     = colors.HexColor('#f0fdf4')
    TUTORIAL_BG= colors.HexColor('#fdf4ff')
    NPTEL_BG   = colors.HexColor('#fef3c7')
    LUNCH_BG   = colors.HexColor('#fff7ed')
    G1_HDR     = colors.HexColor('#dbeafe')
    G2_HDR     = colors.HexColor('#dcfce7')
    BOTH_HDR   = colors.HexColor('#f0f7ff')

    def _compact(ts, prefix=None):
        """Return (line1, line2) compact strings for a timeslot."""
        code_part = f"{ts.subject.code} · " if ts.subject.code else ""
        line1 = f"{code_part}{ts.subject.name}"
        if prefix:
            line1 = f"{prefix} · {line1}"
        room_part = f" · {ts.room.name}" if ts.room else ""
        line2 = f"{ts.professor.name}{room_part}"
        return line1, line2

    slot_labels = ["Day"] + [SLOT_TIMES[s] for s in SLOTS[:5]] + ["Lunch\n1:10-2:00"] + [SLOT_TIMES[s] for s in SLOTS[5:]]
    header_row  = [Paragraph(s.replace('\n', '<br/>'), styles_map['head']) for s in slot_labels]
    rows = [header_row]
    cell_styles = [
        ('BACKGROUND', (0, 0), (-1, 0), BLUE),
        ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (6, 1), (6, len(DAYS)), LUNCH_BG),
        ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#f0f4ff')),
    ]
    for row_idx, day in enumerate(DAYS, start=1):
        row = [Paragraph(f"<b>{day[:3]}</b>", styles_map['day'])]
        for slot in SLOTS:
            col_idx = SLOTS.index(slot) + 1
            if slot > 5:
                col_idx += 1
            ts1 = g1_data[day][slot]
            ts2 = g2_data[day][slot]
            if ts1 or ts2:
                content = []
                same = (ts1 and ts2 and
                        ts1.subject_id == ts2.subject_id and
                        ts1.professor_id == ts2.professor_id)
                if same:
                    st = ts1.subject.subject_type
                    bg = (LAB_BG if st == 'LAB' else
                          TUTORIAL_BG if st == 'TUTORIAL' else
                          NPTEL_BG if st == 'NPTEL' else THEORY_BG)
                    l1, l2 = _compact(ts1)
                    content.append(Paragraph(f"<b>{l1}</b>", s_name))
                    content.append(Paragraph(l2, s_info))
                    content.append(Paragraph("<b>[ G1 + G2 ]</b>", s_div))
                    cell_styles.append(('BACKGROUND', (col_idx, row_idx), (col_idx, row_idx), bg))
                else:
                    if ts1:
                        l1, l2 = _compact(ts1)
                        content.append(Paragraph(
                            f"<font color='#1d4ed8'><b>G1</b></font> <b>{l1}</b>", s_name))
                        content.append(Paragraph(l2, s_info))
                    if ts1 and ts2:
                        content.append(Paragraph("· · ·", s_dash))
                    if ts2:
                        l1, l2 = _compact(ts2)
                        content.append(Paragraph(
                            f"<font color='#15803d'><b>G2</b></font> <b>{l1}</b>", s_name))
                        content.append(Paragraph(l2, s_info))
                    # Background colour
                    if ts1 and ts2:
                        cell_styles.append(('BACKGROUND', (col_idx, row_idx), (col_idx, row_idx), BOTH_HDR))
                    elif ts1:
                        cell_styles.append(('BACKGROUND', (col_idx, row_idx), (col_idx, row_idx), G1_HDR))
                    else:
                        cell_styles.append(('BACKGROUND', (col_idx, row_idx), (col_idx, row_idx), G2_HDR))
                row.append(content)
            else:
                row.append(Paragraph("—", s_info))
            if slot == 5:
                row.append(Paragraph("🍽 Lunch", s_info))
        rows.append(row)

    col_widths = [1.8*cm] + [2.9*cm]*5 + [1.6*cm] + [2.9*cm]*2
    # None = auto-size each row to its tallest cell — no more overflow
    t = Table(rows, colWidths=col_widths, rowHeights=[1.0*cm] + [None]*len(DAYS))
    t.setStyle(TableStyle([
        ('GRID',          (0, 0), (-1, -1), 0.4, colors.HexColor('#dce3f5')),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING',    (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING',   (0, 0), (-1, -1), 3),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 3),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fafbff')]),
    ] + cell_styles))
    return t


def _build_prof_room_pdf_table(raw, styles_map, hdr_color_hex='#1565c0', is_list=True):
    """Beautiful professor/room timetable table with lab colspan.
    is_list=True  → raw[day][slot] = list of TimeSlot
    is_list=False → raw[day][slot] = single TimeSlot or None
    """
    from reportlab.platypus import Table, TableStyle, Paragraph
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    HDR       = colors.HexColor(hdr_color_hex)
    THEORY_BG = colors.HexColor('#EFF6FF')
    LAB_BG    = colors.HexColor('#F0FDF4')
    TUT_BG    = colors.HexColor('#FDF4FF')
    NPTEL_BG  = colors.HexColor('#FEF3C7')
    LUNCH_BG  = colors.HexColor('#FFF7ED')
    DAY_BG    = colors.HexColor('#F1F5F9')
    EMPTY_COL = colors.HexColor('#F8FAFC')
    GRID_COL  = colors.HexColor('#E2E8F0')
    TYPE_LABEL = {'LAB':'🔬 LAB','TUTORIAL':'📘 TUT','NPTEL':'📡 NPTEL','THEORY':'📖 THEORY'}

    def _get(day, slot):
        val = raw[day][slot]
        if is_list:
            return val  # list
        return [val] if val else []

    def _bg(st):
        return LAB_BG if st=='LAB' else TUT_BG if st=='TUTORIAL' else NPTEL_BG if st=='NPTEL' else THEORY_BG

    slot_labels = (["Day"] + [SLOT_TIMES[s] for s in SLOTS[:5]] +
                   ["Lunch\n1:10–2:00"] + [SLOT_TIMES[s] for s in SLOTS[5:]])
    rows = [[Paragraph(s.replace('\n','<br/>'), styles_map['head']) for s in slot_labels]]
    bg_cmds   = [('BACKGROUND',(0,0),(-1,0),HDR),
                 ('BACKGROUND',(6,1),(6,len(DAYS)),LUNCH_BG),
                 ('BACKGROUND',(0,1),(0,-1),DAY_BG)]
    span_cmds = []

    for ri, day in enumerate(DAYS, start=1):
        row = [Paragraph(f"<b>{day[:3]}</b>", styles_map['day'])]
        skip_next = False
        for slot in SLOTS:
            if slot == 6:
                row.append(Paragraph("🍽<br/><b>Lunch</b>", styles_map['prof']))
            if skip_next:
                skip_next = False
                continue
            ci      = _pdf_slot_to_col(slot)
            entries = _get(day, slot)
            next_slot    = slot + 1 if slot < 9 else None
            next_entries = _get(day, next_slot) if next_slot and next_slot != 6 else []
            is_lab_span  = (entries and next_entries and
                            entries[0].subject.subject_type == 'LAB' and
                            next_entries[0].subject.subject_type == 'LAB' and
                            entries[0].subject_id == next_entries[0].subject_id and
                            slot != 5)
            if entries:
                ts = entries[0]
                st = ts.subject.subject_type
                # Section label
                if ts.section:
                    sec_lbl = (f"{ts.section.course.department.name} · "
                               f"{ts.section.get_year_display_label()} · "
                               f"Sec {ts.section.get_effective_section_name()} · {ts.section.group}")
                else:
                    sec_lbl = ""
                # Multiple sections (professor view)
                if len(entries) > 1:
                    seen = set()
                    parts = []
                    for t2 in entries:
                        if t2.section:
                            lbl = f"{t2.section.course.department.name}·{t2.section.get_year_display_label()}·{t2.section.group}"
                            if lbl not in seen:
                                seen.add(lbl)
                                parts.append(lbl)
                    sec_lbl = ", ".join(parts)
                content = []
                if ts.subject.code:
                    content.append(Paragraph(f"<b>{ts.subject.code}</b>", styles_map['prof']))
                content.append(Paragraph(f"<b>{ts.subject.name}</b>", styles_map['cell']))
                if hasattr(ts, 'professor') and ts.professor:
                    content.append(Paragraph(f"👤 {ts.professor.name}", styles_map['prof']))
                if sec_lbl:
                    content.append(Paragraph(sec_lbl, styles_map['prof']))
                if ts.room:
                    content.append(Paragraph(f"🚪 {ts.room.name}", styles_map['prof']))
                content.append(Paragraph(TYPE_LABEL.get(st, st), styles_map['type_tag']))
                row.append(content)
                bg_cmds.append(('BACKGROUND',(ci,ri),(ci,ri),_bg(st)))
                if is_lab_span:
                    span_cmds.append(('SPAN',(ci,ri),(_pdf_slot_to_col(next_slot),ri)))
                    skip_next = True
            else:
                row.append(Paragraph("—", styles_map['prof']))
                bg_cmds.append(('BACKGROUND',(ci,ri),(ci,ri),EMPTY_COL))
        rows.append(row)

    col_widths  = [1.7*cm] + [2.6*cm]*5 + [1.8*cm] + [2.6*cm]*4
    row_heights = [1.0*cm] + [2.2*cm]*len(DAYS)
    t = Table(rows, colWidths=col_widths, rowHeights=row_heights)
    t.setStyle(TableStyle([
        ('GRID',          (0,0),(-1,-1), 0.5, GRID_COL),
        ('BOX',           (0,0),(-1,-1), 1.2, HDR),
        ('LINEBEFORE',    (6,0),(6,-1),  1.0, colors.HexColor('#fed7aa')),
        ('LINEAFTER',     (6,0),(6,-1),  1.0, colors.HexColor('#fed7aa')),
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('ALIGN',         (0,0),(-1,-1), 'CENTER'),
        ('TOPPADDING',    (0,0),(-1,-1), 4),
        ('BOTTOMPADDING', (0,0),(-1,-1), 4),
        ('LEFTPADDING',   (0,0),(-1,-1), 3),
        ('RIGHTPADDING',  (0,0),(-1,-1), 3),
        ('ROWBACKGROUNDS',(0,1),(-1,-1), [colors.white, colors.HexColor('#FAFBFF')]),
        ('FONTNAME',      (0,0),(-1,0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0,0),(-1,0),  7),
        ('TEXTCOLOR',     (0,0),(-1,0),  colors.white),
    ] + bg_cmds + span_cmds))
    return t
    """A coloured banner used as a section divider in the department PDF."""
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    banner_style = ParagraphStyle('banner', fontSize=12, fontName='Helvetica-Bold',
                                  alignment=TA_CENTER, textColor=colors.white)
    from reportlab.platypus import Paragraph as P
    t = Table([[P(text, banner_style)]], colWidths=[27.7*cm], rowHeights=[0.8*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(color_hex)),
        ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING',(0,0),(-1,-1),4),
    ]))
    return t


def export_department_pdf(request, dept_id):
    import os, base64
    from datetime import date
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, PageBreak,
                                    Spacer, Table, TableStyle, Image, HRFlowable)

    dept = get_object_or_404(Department, id=dept_id)
    styles_map = _get_pdf_styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=1*cm, rightMargin=1*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)

    cover_title  = ParagraphStyle('ct',  fontSize=22, fontName='Helvetica-Bold',
                                  alignment=TA_CENTER, textColor=colors.HexColor('#1a56db'), spaceAfter=8)
    cover_sub    = ParagraphStyle('cs',  fontSize=12, fontName='Helvetica',
                                  alignment=TA_CENTER, textColor=colors.HexColor('#607d8b'), spaceAfter=6)
    cover_date   = ParagraphStyle('cd',  fontSize=9,  fontName='Helvetica',
                                  alignment=TA_CENTER, textColor=colors.grey)
    toc_style    = ParagraphStyle('toc', fontSize=10, fontName='Helvetica',
                                  alignment=TA_LEFT,   textColor=colors.HexColor('#1c2333'), leading=18)
    legend_style = ParagraphStyle('leg', fontSize=8,  fontName='Helvetica',
                                  alignment=TA_LEFT,   textColor=colors.HexColor('#607d8b'))

    elements = []

    # ── COVER PAGE ──────────────────────────────────────────────────────────
    logo_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'agclogo.jpg')
    if os.path.exists(logo_path):
        elements.append(Spacer(1, 1.2*cm))
        elements.append(Image(logo_path, width=3.5*cm, height=3.5*cm, hAlign='CENTER'))
        elements.append(Spacer(1, 0.5*cm))
    else:
        elements.append(Spacer(1, 2*cm))

    elements += [
        Paragraph("GTM SmartSchedule", cover_sub),
        Paragraph(f"{dept.name}", cover_title),
        Paragraph("Department Timetable Report", cover_sub),
        HRFlowable(width="80%", thickness=1.5, color=colors.HexColor('#1a56db'), hAlign='CENTER'),
        Spacer(1, 0.4*cm),
        Paragraph(f"Generated on: {date.today().strftime('%d %B %Y')}", cover_date),
        Spacer(1, 0.8*cm),
    ]

    # Table of Contents box
    all_sections = list(Section.objects.filter(course__department=dept)
                        .select_related('course').order_by('course__name','year','section_name','group'))
    all_professors = list(Professor.objects.filter(
        timeslot__section__course__department=dept
    ).distinct().order_by('name'))
    lab_rooms = list(Room.objects.filter(department=dept, room_type='LAB').order_by('name'))
    if not lab_rooms:
        lab_rooms = list(Room.objects.filter(room_type='LAB').order_by('name'))

    toc_rows = []
    if all_sections:
        toc_rows.append(("Part 1", "Individual Group Class Timetables",
                         f"{len(all_sections)} section(s)"))
    # build combined groups list
    from itertools import groupby
    sec_key = lambda s: (s.course_id, s.year, s.section_name)
    combined_groups = []
    for key, grp in groupby(sorted(all_sections, key=sec_key), key=sec_key):
        grp_list = list(grp)
        if len(grp_list) >= 2:
            combined_groups.append(grp_list)
    if combined_groups:
        toc_rows.append(("Part 2", "Combined Timetables (G1 + G2)",
                         f"{len(combined_groups)} section(s)"))
    if all_professors:
        toc_rows.append(("Part 3", "Professor Schedules",
                         f"{len(all_professors)} professor(s)"))
    if lab_rooms:
        toc_rows.append(("Part 4", "Lab Room Schedules",
                         f"{len(lab_rooms)} lab(s)"))

    if toc_rows:
        toc_data = [["Part", "Contents", "Count"]] + toc_rows
        toc_col_w = [2.5*cm, 16*cm, 5*cm]
        toc_t = Table(toc_data, colWidths=toc_col_w)
        toc_t.setStyle(TableStyle([
            ('BACKGROUND',   (0,0),(-1,0), colors.HexColor('#1a56db')),
            ('TEXTCOLOR',    (0,0),(-1,0), colors.white),
            ('FONTNAME',     (0,0),(-1,0), 'Helvetica-Bold'),
            ('FONTSIZE',     (0,0),(-1,-1), 9),
            ('FONTNAME',     (0,1),(-1,-1), 'Helvetica'),
            ('BACKGROUND',   (0,1),(-1,-1), colors.HexColor('#f8faff')),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#f8faff'), colors.white]),
            ('GRID',         (0,0),(-1,-1), 0.4, colors.HexColor('#dce3f5')),
            ('VALIGN',       (0,0),(-1,-1), 'MIDDLE'),
            ('TOPPADDING',   (0,0),(-1,-1), 6),
            ('BOTTOMPADDING',(0,0),(-1,-1), 6),
            ('ALIGN',        (2,0),(-1,-1), 'CENTER'),
        ]))
        elements.append(toc_t)

    # Legend
    elements.append(Spacer(1, 0.5*cm))
    legend_items = [
        (colors.HexColor('#eff6ff'), "Theory"),
        (colors.HexColor('#f0fdf4'), "Lab"),
        (colors.HexColor('#fdf4ff'), "Tutorial"),
        (colors.HexColor('#fef3c7'), "NPTEL"),
        (colors.HexColor('#dbeafe'), "G1 Only"),
        (colors.HexColor('#dcfce7'), "G2 Only"),
    ]
    leg_data = [[Table([[Paragraph(name, legend_style)]],
                       colWidths=[2.2*cm],
                       style=TableStyle([('BACKGROUND',(0,0),(-1,-1), bg),
                                        ('GRID',(0,0),(-1,-1),0.4,colors.HexColor('#dce3f5')),
                                        ('TOPPADDING',(0,0),(-1,-1),3),
                                        ('BOTTOMPADDING',(0,0),(-1,-1),3)]))
                for bg, name in legend_items]]
    leg_table = Table([leg_data], colWidths=[2.4*cm]*len(legend_items))
    elements.append(leg_table)
    elements.append(PageBreak())

    # ── PART 1: INDIVIDUAL GROUP CLASS TIMETABLES ────────────────────────────
    if all_sections:
        elements.append(_build_section_header("Part 1 — Individual Group Class Timetables", styles_map, '#1a56db'))
        elements.append(Spacer(1, 0.3*cm))
        for i, section in enumerate(all_sections):
            if i > 0:
                elements.append(PageBreak())
            yd = section.get_year_display_label()
            label = (f"{dept.name}  ·  {section.course.get_display_name()}  ·  {yd}"
                     f"  ·  Sec {section.get_effective_section_name()}  ·  {section.get_group_display()}")
            data = _build_tt_data(section)
            elements.append(Paragraph(label, styles_map['section_title']))
            elements.append(Paragraph("Weekly Class Timetable  (Code · Subject · Professor · Room)", styles_map['sub']))
            elements.append(_build_pdf_table(data, label, styles_map))

    # ── PART 2: COMBINED (G1+G2) TIMETABLES ─────────────────────────────────
    if combined_groups:
        elements.append(PageBreak())
        elements.append(_build_section_header("Part 2 — Combined Timetables (G1 + G2)", styles_map, '#6d28d9'))
        elements.append(Spacer(1, 0.3*cm))
        for idx, grp_list in enumerate(combined_groups):
            if idx > 0:
                elements.append(PageBreak())
            # Find G1 and G2
            g_map = {s.group: s for s in grp_list}
            g1 = g_map.get('G1') or grp_list[0]
            g2 = g_map.get('G2') or grp_list[1]
            yd  = g1.get_year_display_label()
            sec = g1.get_effective_section_name()
            label = (f"{dept.name}  ·  {g1.course.get_display_name()}  ·  {yd}"
                     f"  ·  Sec {sec}  —  G1 + G2 Combined")
            g1_data = _build_tt_data(g1)
            g2_data = _build_tt_data(g2)
            elements.append(Paragraph(label, styles_map['section_title']))
            elements.append(Paragraph(
                "Shared theory shown once (G1+G2) · Group-specific entries labelled G1 / G2  "
                "·  (Code · Subject · Professor · Room)",
                styles_map['sub']))
            elements.append(_build_combined_pdf_table(g1_data, g2_data, styles_map))

    # ── PART 3: PROFESSOR SCHEDULES ──────────────────────────────────────────
    if all_professors:
        elements.append(PageBreak())
        elements.append(_build_section_header("Part 3 — Professor Schedules", styles_map, '#065f46'))
        elements.append(Spacer(1, 0.3*cm))
        for pi, professor in enumerate(all_professors):
            if pi > 0:
                elements.append(PageBreak())
            raw = {day: {slot: [] for slot in SLOTS} for day in DAYS}
            for ts in TimeSlot.objects.filter(professor=professor).select_related(
                    'subject', 'section__course__department', 'room'):
                if ts.day in raw and ts.slot in raw[ts.day]:
                    raw[ts.day][ts.slot].append(ts)
            el_label = f" · {professor.email}" if professor.email else ""
            elements.append(Paragraph(f"Prof. {professor.name}{el_label}", styles_map['section_title']))
            elements.append(Paragraph("Weekly Teaching Schedule  (Code · Subject · Section · Room)", styles_map['sub']))
            elements.append(_build_prof_room_pdf_table(raw, styles_map, '#065f46', is_list=True))

    # ── PART 4: LAB ROOM SCHEDULES ───────────────────────────────────────────
    if lab_rooms:
        elements.append(PageBreak())
        elements.append(_build_section_header("Part 4 — Lab Room Schedules", styles_map, '#92400e'))
        elements.append(Spacer(1, 0.3*cm))
        for li, room in enumerate(lab_rooms):
            if li > 0:
                elements.append(PageBreak())
            schedule = {day: {slot: None for slot in SLOTS} for day in DAYS}
            for ts in TimeSlot.objects.filter(room=room).select_related(
                    'subject', 'professor', 'section__course__department'):
                if ts.day in schedule and ts.slot in schedule[ts.day]:
                    schedule[ts.day][ts.slot] = ts
            dept_tag = f" [{room.department.name}]" if room.department else " [Shared]"
            elements.append(Paragraph(f"Lab: {room.name}{dept_tag}  ·  Capacity: {room.capacity}", styles_map['section_title']))
            elements.append(Paragraph("Lab Room Schedule  (Code · Subject · Professor · Section)", styles_map['sub']))
            elements.append(_build_prof_room_pdf_table(schedule, styles_map, '#92400e', is_list=False))

    if not any([all_sections, all_professors, lab_rooms]):
        elements = [Paragraph(f"No timetable data found for {dept.name}.", styles_map['sub'])]

    doc.build(elements)
    buffer.seek(0)
    fname = f"dept_timetable_{dept.name}.pdf".replace(' ', '_')
    resp = HttpResponse(buffer, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


def export_room_pdf(request, room_id):
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    room = get_object_or_404(Room, id=room_id)
    styles_map = _get_pdf_styles()
    schedule = {day: {slot: None for slot in SLOTS} for day in DAYS}
    for ts in TimeSlot.objects.filter(room=room).select_related(
            'subject', 'professor', 'section__course__department'):
        if ts.day in schedule and ts.slot in schedule[ts.day]:
            schedule[ts.day][ts.slot] = ts
    hdr_color = '#92400e' if room.room_type == 'LAB' else '#1565c0'
    rl  = "Lab" if room.room_type == 'LAB' else "Classroom"
    dpt = f" · {room.department.name}" if room.department else " · Shared"
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=1.2*cm, rightMargin=1.2*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    elements = [
        Paragraph(f"{rl}: {room.name}{dpt} — Weekly Schedule", styles_map['title']),
        Paragraph(f"Capacity: {room.capacity}  ·  Auto-generated Room Schedule", styles_map['sub']),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor(hdr_color), spaceAfter=8),
        _build_prof_room_pdf_table(schedule, styles_map, hdr_color, is_list=False),
    ]
    doc.build(elements)
    buffer.seek(0)
    fname = f"room_schedule_{room.name}.pdf".replace(' ', '_')
    resp = HttpResponse(buffer, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


def export_professor_pdf(request, professor_id):
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, HRFlowable
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    professor = get_object_or_404(Professor, id=professor_id)

    # ── Styles ──────────────────────────────────────────────────────────────
    NAVY       = colors.HexColor('#1e3a5f')
    BLUE       = colors.HexColor('#1565c0')
    BLUE_LIGHT = colors.HexColor('#e8f0fe')
    THEORY_BG  = colors.HexColor('#EFF6FF')
    THEORY_BD  = colors.HexColor('#BFDBFE')
    LAB_BG     = colors.HexColor('#F0FDF4')
    LAB_BD     = colors.HexColor('#86EFAC')
    TUT_BG     = colors.HexColor('#FDF4FF')
    TUT_BD     = colors.HexColor('#E9D5FF')
    LUNCH_BG   = colors.HexColor('#FFF7ED')
    GRID_COL   = colors.HexColor('#E2E8F0')
    DAY_BG     = colors.HexColor('#F1F5F9')
    EMPTY_COL  = colors.HexColor('#F8FAFC')
    WHITE      = colors.white

    def style(name, **kw):
        defaults = dict(fontName='Helvetica', fontSize=7, alignment=TA_CENTER, leading=9)
        defaults.update(kw)
        return ParagraphStyle(name, **defaults)

    S = {
        'title':  style('ti', fontSize=15, fontName='Helvetica-Bold', alignment=TA_CENTER, textColor=NAVY, spaceAfter=2, leading=18),
        'sub':    style('su', fontSize=8,  fontName='Helvetica',      alignment=TA_CENTER, textColor=colors.HexColor('#64748b'), spaceAfter=14),
        'head':   style('hd', fontSize=7,  fontName='Helvetica-Bold', alignment=TA_CENTER, textColor=WHITE, leading=9),
        'day':    style('dy', fontSize=8,  fontName='Helvetica-Bold', alignment=TA_CENTER, textColor=NAVY),
        'subj':   style('sb', fontSize=7,  fontName='Helvetica-Bold', alignment=TA_CENTER, textColor=NAVY, leading=9),
        'meta':   style('mt', fontSize=5.5,fontName='Helvetica',      alignment=TA_CENTER, textColor=colors.HexColor('#475569'), leading=7),
        'type':   style('tp', fontSize=5,  fontName='Helvetica-Bold', alignment=TA_CENTER, textColor=colors.HexColor('#6b7280'), leading=6),
        'lunch':  style('ln', fontSize=6,  fontName='Helvetica-Bold', alignment=TA_CENTER, textColor=colors.HexColor('#c2410c'), leading=8),
        'empty':  style('em', fontSize=7,  fontName='Helvetica',      alignment=TA_CENTER, textColor=colors.HexColor('#cbd5e1')),
    }

    # ── Collect timeslots ────────────────────────────────────────────────────
    raw = {day: {slot: [] for slot in SLOTS} for day in DAYS}
    for ts in TimeSlot.objects.filter(professor=professor).select_related('subject', 'section__course__department', 'room'):
        if ts.day in raw and ts.slot in raw[ts.day]:
            raw[ts.day][ts.slot].append(ts)

    # SLOTS = [1..9], slot 6+ are afternoon (slot 5 = last before lunch)
    # Table columns: Day | s1 | s2 | s3 | s4 | s5 | Lunch | s6 | s7 | s8 | s9
    # col indices:    0     1    2    3    4    5     6       7    8    9    10

    def slot_to_col(slot):
        return slot if slot <= 5 else slot + 1  # +1 for lunch column

    def cell_content(entries, slot):
        """Return (paragraphs_list, bg_color, border_color, type_str)"""
        if not entries:
            return [Paragraph("—", S['empty'])], EMPTY_COL, GRID_COL, None
        ts = entries[0]
        st = ts.subject.subject_type
        bg = LAB_BG if st == 'LAB' else (TUT_BG if st == 'TUTORIAL' else THEORY_BG)
        bd = LAB_BD if st == 'LAB' else (TUT_BD if st == 'TUTORIAL' else THEORY_BD)
        type_label = '🔬 LAB' if st == 'LAB' else ('📘 TUT' if st == 'TUTORIAL' else ('📡 NPTEL' if st == 'NPTEL' else '📖 THEORY'))

        sec_parts = []
        seen = set()
        for t in entries:
            if t.section:
                lbl = f"{t.section.course.department.name} · {t.section.get_year_display_label()} · {t.section.group}"
                if lbl not in seen:
                    seen.add(lbl)
                    sec_parts.append(lbl)
        sec_text = ", ".join(sec_parts)
        room_text = f"🚪 {ts.room.name}" if ts.room else ""

        content = [Paragraph(f"<b>{ts.subject.name}</b>", S['subj'])]
        if sec_text: content.append(Paragraph(sec_text, S['meta']))
        if room_text: content.append(Paragraph(room_text, S['meta']))
        content.append(Paragraph(type_label, S['type']))
        return content, bg, bd, st

    # ── Build rows with lab colspan ──────────────────────────────────────────
    slot_labels = (
        ["Day"] +
        [SLOT_TIMES[s] for s in SLOTS[:5]] +
        ["Lunch\n1:10–2:00"] +
        [SLOT_TIMES[s] for s in SLOTS[5:]]
    )
    header_row = [Paragraph(s.replace('\n', '<br/>'), S['head']) for s in slot_labels]
    rows = [header_row]
    span_cmds = []   # SPAN commands for lab 2-col merge
    bg_cmds   = []
    bd_cmds   = []

    for ri, day in enumerate(DAYS, start=1):
        row = [Paragraph(f"<b>{day[:3]}</b>", S['day'])]
        skip_next = False
        col_idx = 1  # start after Day col

        for si, slot in enumerate(SLOTS):
            if slot == 6:
                row.append(Paragraph("🍽<br/><b>Lunch</b>", S['lunch']))
                bg_cmds.append(('BACKGROUND', (6, ri), (6, ri), LUNCH_BG))
                col_idx += 1  # skip lunch col count

            if skip_next:
                skip_next = False
                col_idx += 1
                continue

            entries = raw[day][slot]
            ci = slot_to_col(slot)

            # Check if lab spans this + next slot
            is_lab = entries and entries[0].subject.subject_type == 'LAB'
            next_slot = slot + 1 if slot < 9 else None
            next_entries = raw[day][next_slot] if next_slot and next_slot != 6 else []
            next_is_same_lab = (
                is_lab and next_entries and
                next_entries[0].subject.subject_type == 'LAB' and
                next_entries[0].subject.id == entries[0].subject.id and
                next_entries[0].section.id == entries[0].section.id
            )

            content, bg, bd, stype = cell_content(entries, slot)
            row.append(content)
            bg_cmds.append(('BACKGROUND', (ci, ri), (ci, ri), bg))

            if next_is_same_lab and slot != 5:
                # Merge this cell with next column
                ci_next = slot_to_col(next_slot)
                span_cmds.append(('SPAN', (ci, ri), (ci_next, ri)))
                skip_next = True

            col_idx += 1

        rows.append(row)

    # ── Column widths ────────────────────────────────────────────────────────
    # Day | 5 morning slots | Lunch | 4 afternoon slots
    col_widths = [1.7*cm] + [2.6*cm]*5 + [1.8*cm] + [2.6*cm]*4
    row_heights = [1.0*cm] + [2.2*cm]*len(DAYS)

    t = Table(rows, colWidths=col_widths, rowHeights=row_heights)

    base_style = [
        # Header
        ('BACKGROUND',   (0, 0),  (-1, 0),  BLUE),
        ('TEXTCOLOR',    (0, 0),  (-1, 0),  WHITE),
        ('FONTNAME',     (0, 0),  (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0),  (-1, 0),  7),
        # Day column
        ('BACKGROUND',   (0, 1),  (0, -1),  DAY_BG),
        ('FONTNAME',     (0, 1),  (0, -1),  'Helvetica-Bold'),
        # Lunch column
        ('BACKGROUND',   (6, 1),  (6, -1),  LUNCH_BG),
        # Grid
        ('GRID',         (0, 0),  (-1, -1), 0.5, GRID_COL),
        ('BOX',          (0, 0),  (-1, -1), 1.0, BLUE),
        ('LINEBEFORE',   (6, 0),  (6, -1),  1.0, colors.HexColor('#fed7aa')),
        ('LINEAFTER',    (6, 0),  (6, -1),  1.0, colors.HexColor('#fed7aa')),
        # Alignment & padding
        ('VALIGN',       (0, 0),  (-1, -1), 'MIDDLE'),
        ('ALIGN',        (0, 0),  (-1, -1), 'CENTER'),
        ('TOPPADDING',   (0, 0),  (-1, -1), 4),
        ('BOTTOMPADDING',(0, 0),  (-1, -1), 4),
        ('LEFTPADDING',  (0, 0),  (-1, -1), 3),
        ('RIGHTPADDING', (0, 0),  (-1, -1), 3),
    ] + bg_cmds + span_cmds

    t.setStyle(TableStyle(base_style))

    # ── Build doc ────────────────────────────────────────────────────────────
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.2*cm, rightMargin=1.2*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm
    )
    el = f"  ·  {professor.email}" if professor.email else ""
    elements = [
        Paragraph(f"Prof. {professor.name} — Weekly Teaching Schedule", S['title']),
        Paragraph(f"Auto-generated Timetable{el}", S['sub']),
        HRFlowable(width="100%", thickness=1, color=BLUE, spaceAfter=8),
        t,
    ]
    doc.build(elements)
    buffer.seek(0)
    fname = f"professor_schedule_{professor.name}.pdf".replace(' ', '_')
    resp = HttpResponse(buffer, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp
    resp = HttpResponse(buffer, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{fname}"'
    return resp


def qr_timetable(request, section_id):
    section = get_object_or_404(Section, id=section_id)
    return HttpResponse(_make_qr_png(request.build_absolute_uri(f'/timetable/{section_id}/'), str(section)), content_type='image/png')

def qr_professor(request, professor_id):
    professor = get_object_or_404(Professor, id=professor_id)
    return HttpResponse(_make_qr_png(request.build_absolute_uri(f'/professor/{professor_id}/'), professor.name), content_type='image/png')


# ═══════════════════════════════════════════════════════════════════════════════
# CSV UPLOAD VIEW
# ═══════════════════════════════════════════════════════════════════════════════

def csv_upload(request):
    """Upload multiple CSVs, import data, optionally auto-generate timetable."""
    form = CSVUploadForm(request.POST or None, request.FILES or None)
    recent_logs = CSVImportLog.objects.order_by('-imported_at')[:5]

    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        clear = cd.get('clear_existing', False)

        # Optional data clear
        if clear:
            TimeSlot.objects.all().delete()
            Subject.objects.all().delete()
            Section.objects.all().delete()
            messages.warning(request, '🗑️ Existing timetable, subjects and sections cleared.')

        files_dict = {}
        if cd.get('subjects_csv'):    files_dict['subjects']      = cd['subjects_csv']
        if cd.get('professors_csv'):  files_dict['professors']    = cd['professors_csv']
        if cd.get('rooms_csv'):       files_dict['rooms']         = cd['rooms_csv']
        if cd.get('sections_csv'):    files_dict['sections']      = cd['sections_csv']
        if cd.get('dept_settings_csv'): files_dict['dept_settings'] = cd['dept_settings_csv']

        counts, errors, warnings_list = run_full_import(files_dict)

        # Save log
        status = 'FAILED' if errors and not any(counts.values()) else \
                 'PARTIAL' if errors else 'SUCCESS'
        log = CSVImportLog.objects.create(
            status=status,
            subjects_created=counts['subjects'],
            professors_created=counts['professors'],
            rooms_created=counts['rooms'],
            sections_created=counts['sections'],
            errors='\n'.join(errors),
            warnings='\n'.join(warnings_list),
        )

        # Show summary messages
        parts = []
        if counts['rooms']:       parts.append(f"{counts['rooms']} rooms")
        if counts['professors']:  parts.append(f"{counts['professors']} professors")
        if counts['sections']:    parts.append(f"{counts['sections']} sections")
        if counts['subjects']:    parts.append(f"{counts['subjects']} subject entries")
        if parts:
            messages.success(request, f"✅ Imported: {', '.join(parts)}.")
        for w in warnings_list:
            messages.warning(request, f"⚠️ {w}")
        for e in errors:
            messages.error(request, f"❌ {e}")

        # Auto-generate timetable
        if cd.get('auto_generate') and not errors:
            return redirect('generate_smart')

        return redirect('csv_upload')

    return render(request, 'csv_upload.html', {'form': form, 'recent_logs': recent_logs})


def csv_download_template(request, template_name):
    """Download a sample CSV template."""
    templates = {
        'subjects': {
            'filename': 'subjects_template.csv',
            'rows': [
                'subject_id,subject_name,sub_type,theory_per_week,lab_per_week,tutorial_per_week,allowed_groups,specialization_required,course,academic_year',
                '# sub_type: DEPARTMENT (for theory/lab/tutorial) or NPTL (for NPTEL subjects)',
                '# allowed_groups: G1 / G2 / G1 G2 (for both)',
                '# specialization_required: YES / NO',
                '# course: e.g. B.TECH   academic_year: e.g. 2ND / 3RD',
                'CS303,DBMS,DEPARTMENT,3,2,1,G1 G2,NO,B.TECH,2ND',
                'CS305,Machine Learning,DEPARTMENT,3,0,0,G1 G2,YES,B.TECH,3RD',
                'CS102,PYTHON,NPTL,0,1,0,G1 G2,NO,B.TECH,2ND',
            ]
        },
        'professors': {
            'filename': 'professors_template.csv',
            'rows': [
                'professor_id,professor_name,max_workload_hours_per_week,specialization_subjects,SUB_CAN_TEACH_FOR_SPECIFIC_CLASS,block_time_slot(day/time)',
                '# SUB_CAN_TEACH_FOR_SPECIFIC_CLASS: DEPT,COURSE,YEAR,SEC  (leave blank for all sections)',
                '# block_time_slot: Day,HH:MM to HH:MM  e.g. Tuesday,9:50 to 11:30  |  use | to add multiple blocks',
                'P001,Dr. Sharma,20,Machine Learning,"CSE,BTECH,2 YEAR,SEC-A","Tuesday,9:50 to 11:30"',
                'P002,Dr. Kaur,18,OS Lab,,',
                'P003,Prof. Singh,20,Machine Learning,,"Monday,9:00 to 9:50|Friday,2:00 to 2:50"',
            ]
        },
        'rooms': {
            'filename': 'rooms_template.csv',
            'rows': [
                'room_id,room_name,room_type,capacity,allowed_subjects',
                'R001,Room 101,classroom,60,all',
                'R002,CS Lab 1,lab,30,OS Lab,DBMS Lab',
                'R003,CS Lab 2,lab,30,all',
                'R004,Room 102,classroom,60,all',
            ]
        },
        'sections': {
            'filename': 'sections_template.csv',
            'rows': [
                'department,year,section,group,fixed_room,course,free_day,class_count,section_start_time',
                '# course: B.TECH / BE / M.TECH (leave blank to default to B.TECH)',
                '# free_day: Monday / Tuesday / Wednesday / Thursday / Friday (leave blank for no holiday)',
                '# class_count: number of students (used to auto-assign a room with enough capacity)',
                '# section_start_time: HH:MM format e.g. 09:00 / 09:50 (leave blank to use department default)',
                'CSE,2nd,A,G1,Room 101,B.TECH,Wednesday,25,09:00',
                'CSE,2nd,A,G2,Room 101,B.TECH,Wednesday,22,09:00',
                'CSE,2nd,B,G1,,B.TECH,Thursday,28,09:00',
                'CSE,2nd,B,G2,,B.TECH,Thursday,30,09:50',
            ]
        },
        'dept_settings': {
            'filename': 'dept_settings_template.csv',
            'rows': [
                'department,lunch_start_time,lunch_end_time,department_start_time',
                '# lunch_start_time / lunch_end_time: slot number (1-8) OR HH:MM start time of slot',
                '# department_start_time: slot number (1-8) OR HH:MM start time (e.g. 9:00 or 10:40). Leave blank for default (9:00)',
                'CSE,5,5,',
                'IT,5,5,9:00',
                'ECE,12:20,1:10,10:40',
            ]
        },
    }
    tmpl = templates.get(template_name)
    if not tmpl:
        return HttpResponse('Template not found', status=404)
    content = '\n'.join(tmpl['rows']) + '\n'
    resp = HttpResponse(content, content_type='text/csv')
    resp['Content-Disposition'] = f'attachment; filename="{tmpl["filename"]}"'
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# SMART TIMETABLE GENERATION (enhanced with all constraints)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_timetable_smart(request):
    """
    Enhanced timetable generation with:
    - Professor workload limits
    - Lab room subject restrictions
    - Professor specialization matching
    - Fixed room for sections
    - Department lunch break settings
    - Balanced workload distribution
    - Clash detection with warnings
    """
    TimeSlot.objects.all().delete()

    all_sections = list(Section.objects.prefetch_related(
        'subjects__professors', 'subjects__lab_room', 'fixed_room'
    ).select_related('course__department').all())

    if not all_sections:
        messages.error(request, '❌ No sections found. Add sections or import via CSV first.')
        return redirect('dashboard')

    all_rooms = list(Room.objects.select_related('department').all())
    all_classrooms = [r for r in all_rooms if r.room_type == 'CLASSROOM']
    all_labs = [r for r in all_rooms if r.room_type == 'LAB']

    # ── Per-department settings ────────────────────────────────────────────────
    dept_settings_cache = {}
    def get_dept_settings(dept_id):
        if dept_id not in dept_settings_cache:
            try:
                ds = DepartmentSettings.objects.get(department_id=dept_id)
            except DepartmentSettings.DoesNotExist:
                ds = None
            dept_settings_cache[dept_id] = ds
        return dept_settings_cache[dept_id]

    def get_working_days(dept_id):
        ds = get_dept_settings(dept_id)
        return ds.get_working_days() if ds else DAYS[:]

    def get_lunch_slots(dept_id):
        ds = get_dept_settings(dept_id)
        return ds.get_lunch_slots() if ds else []

    def get_dept_start_slot(dept_id):
        ds = get_dept_settings(dept_id)
        return ds.get_start_slot() if ds else 1

    # ── Room priority ordering ─────────────────────────────────────────────────
    def get_dept_rooms(room_list, dept_id):
        assigned = [r for r in room_list if r.department_id == dept_id]
        shared   = [r for r in room_list if r.department_id is None]
        others   = [r for r in room_list if r.department_id and r.department_id != dept_id]
        return assigned + shared + others

    # ── Room availability tracking ─────────────────────────────────────────────
    room_busy = {}
    def is_room_free(room_id, day, slot, slots_needed=1):
        return all((room_id, day, slot + i) not in room_busy for i in range(slots_needed))

    def get_free_room(room_list, day, slot, slots_needed=1, subject_name='', subject_code='', min_capacity=0):
        # 2-tier priority: preferred rooms (subject match) first, free fallback rooms second.
        # min_capacity: if set, only rooms with capacity >= min_capacity are considered.
        # Among valid rooms, prefer the smallest sufficient one (less wastage).
        preferred, fallback = [], []
        for room in room_list:
            if not is_room_free(room.id, day, slot, slots_needed):
                continue
            if min_capacity and room.capacity < min_capacity:
                continue  # room too small for this section
            if room.room_type == 'LAB' and (subject_name or subject_code):
                if room.can_host_subject(subject_name, subject_code):
                    preferred.append(room)
                else:
                    fallback.append(room)
            else:
                preferred.append(room)
        candidates = preferred if preferred else fallback
        if candidates and min_capacity:
            candidates.sort(key=lambda r: r.capacity)
        return candidates[0] if candidates else None

    def mark_room_busy(room, day, slot, slots_needed=1):
        if room:
            for i in range(slots_needed):
                room_busy[(room.id, day, slot + i)] = True

    # ── Professor availability & workload tracking ─────────────────────────────
    professor_busy = {}
    professor_mins = defaultdict(int)   # prof_id → total minutes scheduled

    def is_prof_free(prof_id, day, slot):
        return (day, slot) not in professor_busy.get(prof_id, set())

    def mark_prof_busy(prof_id, day, slot, slot_mins=50):
        professor_busy.setdefault(prof_id, set()).add((day, slot))
        professor_mins[prof_id] += slot_mins  # 50 min per theory/tutorial, 100 per lab slot

    def prof_within_workload(prof):
        # max_workload_hours_per_week × 60 = total allowed minutes
        max_mins = prof.max_workload_hours_per_week * 60
        return professor_mins[prof.id] < max_mins

    def prof_remaining_mins(prof):
        max_mins = prof.max_workload_hours_per_week * 60
        return max(0, max_mins - professor_mins[prof.id])

    # ── Pick best eligible professor ──────────────────────────────────────────
    def pick_professor(subject, day, *slots, slot_type='theory'):
        """Return a professor who: is free on all slots, within workload, and eligible."""
        profs = list(subject.professors.all())
        if not profs:
            return None
        # Filter by specialization
        if subject.specialization_required:
            eligible = [p for p in profs if p.can_teach_specialized(subject.name, subject.code)]
            if not eligible:
                eligible = profs  # fallback
        else:
            eligible = profs
        # Calculate mins this assignment will consume
        slot_mins = 100 if slot_type == 'lab' else 50
        needed_mins = slot_mins * len(slots)
        # Filter by availability AND strict workload limit
        free = [
            p for p in eligible
            if all(is_prof_free(p.id, day, s) for s in slots)
            and prof_remaining_mins(p) >= needed_mins
        ]
        if not free:
            # Relax workload limit as last resort (avoid total skip)
            free = [p for p in eligible if all(is_prof_free(p.id, day, s) for s in slots)]
        if not free:
            return None
        # Pick least-loaded professor for balanced distribution
        return min(free, key=lambda p: professor_mins[p.id])

    # ── Pre-block occupied times ───────────────────────────────────────────────
    for occ in ProfessorOccupiedTime.objects.select_related('professor').all():
        for slot in occ.blocked_slots():
            mark_prof_busy(occ.professor_id, occ.day, slot)

    for rocc in RoomOccupiedTime.objects.select_related('room').all():
        for slot in rocc.blocked_slots():
            mark_room_busy(rocc.room, rocc.day, slot)

    # ── Pre-block fixed rooms for non-theory use ──────────────────────────────
    # (Fixed rooms are reserved for their section's theory; no pre-blocking needed
    #  — we just prefer them when assigning theory slots.)

    total_created = 0
    skipped = []
    clash_warnings = []
    no_room_warn = []

    # Group sections into pairs (G1+G2 of same course/year/section)
    pair_map = defaultdict(list)
    for sec in all_sections:
        pair_map[(sec.course_id, sec.year, sec.section_name)].append(sec)

    for pair_key, sections_in_pair in pair_map.items():
        dept_id = sections_in_pair[0].course.department_id
        w_days = get_working_days(dept_id)
        lunch_slots = get_lunch_slots(dept_id)
        dept_start = get_dept_start_slot(dept_id)
        dept_classrooms = get_dept_rooms(all_classrooms, dept_id)
        dept_labs = get_dept_rooms(all_labs, dept_id)

        # ── Free-day constraint per section ──────────────────────────────────
        # Union of free days across the pair (used for joint theory/NPTEL scheduling)
        pair_free_days = set(
            sec.free_day for sec in sections_in_pair if sec.free_day
        )
        # Working days excluding any section's free day (for joint scheduling)
        effective_w_days = [d for d in w_days if d not in pair_free_days]
        if not effective_w_days:
            effective_w_days = w_days[:]  # safety fallback

        # Pre-break slot boundary for slot prioritization
        lunch_start_slot = min(lunch_slots) if lunch_slots else (dept_start + 4)

        # ── Available slots (excluding lunch and slots before start time) ─────
        # section_start_slot overrides dept default if any section in pair has one set
        sec_starts = [sec.section_start_slot for sec in sections_in_pair if sec.section_start_slot]
        effective_start = min(sec_starts) if sec_starts else dept_start
        avail_slots = [s for s in SLOTS if s not in lunch_slots and s >= effective_start]
        nptel_slots = [s for s in NPTEL_SLOTS if s not in lunch_slots and s >= effective_start]

        theory_subjects = {}
        nptel_subjects = {}           # grouped by subject name — same logic as THEORY
        lab_subjects_by_section = defaultdict(list)
        tutorial_subjects_by_section = defaultdict(list)

        for sec in sections_in_pair:
            for subj in sec.subjects.all():
                if not subj.professors.exists():
                    skipped.append(f"{subj.name} ({sec}) — no professor assigned")
                    continue
                ag = subj.allowed_groups
                if ag == 'G1' and sec.group != 'G1':
                    continue
                if ag == 'G2' and sec.group != 'G2':
                    continue

                if subj.subject_type == 'THEORY':
                    key = subj.name
                    if key not in theory_subjects:
                        theory_subjects[key] = {'subj': subj, 'sections': [sec], 'subj_per_sec': {sec.id: subj}}
                    else:
                        theory_subjects[key]['sections'].append(sec)
                        theory_subjects[key]['subj_per_sec'][sec.id] = subj
                        # Always prefer G1's subject as primary — pick_professor
                        # reads from subj.professors.all(), so G1's subject must be
                        # the anchor. After csv_import fix, G1 and G2 share the same
                        # professor, but using G1 as primary is the safety guarantee.
                        if sec.group == 'G1':
                            theory_subjects[key]['subj'] = subj
                elif subj.subject_type == 'LAB':
                    lab_subjects_by_section[sec.id].append(subj)
                elif subj.subject_type == 'TUTORIAL':
                    tutorial_subjects_by_section[sec.id].append(subj)
                elif subj.subject_type == 'NPTEL':
                    # Group both sections under the same subject name (mirrors THEORY logic)
                    key = subj.name
                    if key not in nptel_subjects:
                        nptel_subjects[key] = {'subj': subj, 'sections': [sec], 'subj_per_sec': {sec.id: subj}}
                    else:
                        nptel_subjects[key]['sections'].append(sec)
                        nptel_subjects[key]['subj_per_sec'][sec.id] = subj

        pair_used_slots = {day: set() for day in w_days}


        # ── THEORY SCHEDULING — runs FIRST so G1+G2 get same slot/prof/room ──
        # Theory must be placed before labs to guarantee G1 and G2 attend the
        # same lecture together. Labs then avoid these theory slots via pair_used_slots.
        theory_list = list(theory_subjects.values())
        theory_pool = []
        for t in theory_list:
            for _ in range(t['subj'].lectures_per_week):
                theory_pool.append(t)
        # No shuffle — deterministic; days assigned by least-loaded day first

        # Fill slots across the full day — pre-lunch first, post-lunch as needed.
        # Post-lunch slots (including slot 6) are used when pre-lunch is full.
        PRE_LUNCH_CAP = len(avail_slots)  # allow theory to spill into post-lunch
        theory_day_assignments = defaultdict(list)
        for t in theory_pool:
            candidate_days = [d for d in effective_w_days if t not in theory_day_assignments[d]]
            if not candidate_days:
                candidate_days = effective_w_days[:]
            # Prefer days that still have pre-lunch capacity (pack first, then overflow)
            under_cap = [d for d in candidate_days if len(theory_day_assignments[d]) < PRE_LUNCH_CAP]
            pool = under_cap if under_cap else candidate_days
            # Among eligible days, pick the most loaded first (pack, not spread)
            chosen_day = max(pool, key=lambda d: len(theory_day_assignments[d]))
            theory_day_assignments[chosen_day].append(t)

        for day in w_days:
            for t in theory_day_assignments[day]:
                subj = t['subj']
                prof = pick_professor(subj, day, *[s for s in avail_slots if s not in pair_used_slots[day]])
                if not prof:
                    # Try any available slot
                    for s in avail_slots:
                        if s not in pair_used_slots[day]:
                            prof = pick_professor(subj, day, s)
                            if prof:
                                break

                free_slots = sorted(
                    [s for s in avail_slots if s not in pair_used_slots[day]
                     and is_prof_free(prof.id, day, s)]
                ) if prof else []
                if not free_slots or not prof:
                    clash_warnings.append(f"{subj.name} on {day} — no free slot/professor")
                    continue

                # First slot in sorted list = earliest available slot
                chosen_slot = free_slots[0]

                # Fixed room priority: use section's fixed room if set.
                # If room is busy at chosen_slot, try the next available slot
                # so we never leave a slot empty just due to room contention.
                max_cap = max((s.class_count or 0) for s in t['sections'])

                def _find_slot_and_room(candidate_slots):
                    """Return (slot, room) — try each slot until room is found."""
                    for sl in candidate_slots:
                        # Try fixed room first
                        for sec in t['sections']:
                            if sec.fixed_room and is_room_free(sec.fixed_room.id, day, sl):
                                return sl, sec.fixed_room
                        # Try any classroom with sufficient capacity
                        r = get_free_room(dept_classrooms, day, sl, min_capacity=max_cap)
                        if r:
                            return sl, r
                        # Fallback: any classroom regardless of capacity
                        r = get_free_room(dept_classrooms, day, sl)
                        if r:
                            return sl, r
                    return None, None

                remaining_slots = [s for s in free_slots if is_prof_free(prof.id, day, s)]
                chosen_slot, cls_room = _find_slot_and_room(remaining_slots)

                if chosen_slot is None:
                    clash_warnings.append(f"{subj.name} on {day} — professor free but no room available")
                    continue

                for sec in t['sections']:
                    sec_subj = t['subj_per_sec'].get(sec.id, subj)
                    # Skip if section's group doesn't match
                    if subj.allowed_groups == 'G1' and sec.group != 'G1':
                        continue
                    if subj.allowed_groups == 'G2' and sec.group != 'G2':
                        continue
                    TimeSlot.objects.create(
                        day=day, slot=chosen_slot, subject=sec_subj,
                        professor=prof, section=sec, room=cls_room
                    )
                    total_created += 1

                pair_used_slots[day].add(chosen_slot)
                mark_prof_busy(prof.id, day, chosen_slot)
                if cls_room:
                    mark_room_busy(cls_room, day, chosen_slot)
                else:
                    no_room_warn.append(f"No classroom for {subj.name} on {day}")

        # ── NPTEL SCHEDULING (slot 6 first, then 7,8,9 — all post-lunch) ────────
        # Both groups get the same professor, room, and time slot (mirrors THEORY logic).
        nptel_list = list(nptel_subjects.values())
        nptel_pool = []
        for n in nptel_list:
            for _ in range(n['subj'].lectures_per_week):
                nptel_pool.append(n)
        random.shuffle(nptel_pool)

        for n in nptel_pool:
            nsubj = n['subj']
            placed = False
            candidates = []
            for day in effective_w_days:
                for s in nptel_slots:
                    if s not in pair_used_slots[day]:
                        candidates.append((day, s))
            candidates.sort(key=lambda x: x[1])  # lowest slot first
            for day, s in candidates:
                if s in pair_used_slots[day]:
                    continue
                prof = pick_professor(nsubj, day, s)
                if not prof:
                    continue
                cls_room = get_free_room(dept_classrooms, day, s)
                # Assign the same slot, professor, and room to ALL sections in the group
                for sec in n['sections']:
                    sec_subj = n['subj_per_sec'].get(sec.id, nsubj)
                    TimeSlot.objects.create(day=day, slot=s, subject=sec_subj,
                                            professor=prof, section=sec, room=cls_room)
                    total_created += 1
                pair_used_slots[day].add(s)
                mark_prof_busy(prof.id, day, s)
                if cls_room:
                    mark_room_busy(cls_room, day, s)
                placed = True
                break
            if not placed:
                clash_warnings.append(f"NPTEL {nsubj.name} — no after-2PM slot")        # ── LAB SCHEDULING ─────────────────────────────────────────────────────
        # RULE: When G1 has a 2-slot lab, G2 must get 2 tutorial slots in the
        # SAME time block (s1, s2) — and vice versa for G2 lab → G1 tutorials.
        # This ensures both groups are always occupied simultaneously.
        #
        # Implementation:
        #   1. Identify partner section (G1↔G2 within same pair).
        #   2. When placing a lab (s1,s2), also place 2 tutorials for the
        #      partner in the same slots. If partner has no pending tutorials,
        #      fall back to normal independent scheduling.

        def _get_partner(sec):
            """Return the other group's section in this pair, or None."""
            partner_group = 'G2' if sec.group == 'G1' else 'G1'
            for s in sections_in_pair:
                if s.group == partner_group:
                    return s
            return None

        def _pending_tutorials(sec):
            """Return list of tutorial Subject objects not yet scheduled for sec.
            Uses a Counter so multi-slot subjects are counted correctly.
            """
            already = Counter(
                TimeSlot.objects.filter(section=sec, subject__subject_type='TUTORIAL')
                .values_list('subject_id', flat=True)
            )
            tuts = tutorial_subjects_by_section.get(sec.id, [])
            pending = []
            for t in tuts:
                needed = max(0, t.lectures_per_week - already[t.id])
                for _ in range(needed):
                    pending.append(t)
            return pending

        for sec in sections_in_pair:
            lab_subjs = lab_subjects_by_section.get(sec.id, [])
            if not lab_subjs:
                continue
            lab_pool = [ls for ls in lab_subjs for _ in range(ls.lectures_per_week)]
            random.shuffle(lab_pool)
            sec_lab_days_used: set = set()
            is_g1 = sec.group == 'G1'
            preferred_starts = GROUP_ONE_LAB_STARTS if is_g1 else GROUP_TWO_LAB_STARTS
            partner_sec = _get_partner(sec)

            for ls in lab_pool:
                candidates = []
                for day in w_days:
                    if day in sec_lab_days_used:
                        continue
                    if sec.free_day and day == sec.free_day:
                        continue
                    sec_used = set(pair_used_slots[day])
                    for ts_obj in TimeSlot.objects.filter(section=sec, day=day):
                        sec_used.add(ts_obj.slot)

                    valid_pairs = [
                        (s, s + 1) for s in avail_slots
                        if s + 1 in avail_slots
                        and s not in sec_used and s + 1 not in sec_used
                        and s not in LAB_FORBIDDEN_START
                        and s not in lunch_slots and s + 1 not in lunch_slots
                    ]
                    for s1, s2 in valid_pairs:
                        priority = 0 if s1 in preferred_starts else 1
                        candidates.append((priority, day, s1, s2))

                # Sort: priority first (preferred starts), then slot asc across full day
                candidates.sort(key=lambda x: (x[0], x[2]))
                placed = False

                for priority, day, s1, s2 in candidates:
                    sec_used = set(pair_used_slots[day])
                    for ts_obj in TimeSlot.objects.filter(section=sec, day=day):
                        sec_used.add(ts_obj.slot)
                    if s1 in sec_used or s2 in sec_used:
                        continue

                    # ── Check partner availability for simultaneous tutorials ──
                    # RULE: When G1 has a 2-slot lab (s1, s2), G2 should get tutorials
                    # in the SAME time block. We try to fill both slots, but if only
                    # 1 tutorial is pending we place it in s1 (lab still proceeds).
                    # We only BLOCK the lab candidate if the partner's slots are already
                    # occupied (clash) — not because of insufficient tutorials.
                    partner_tuts = []
                    if partner_sec:
                        # Re-fetch partner used slots fresh (avoid stale data)
                        p_used = {ts.slot for ts in TimeSlot.objects.filter(section=partner_sec, day=day)}
                        if s1 in p_used or s2 in p_used:
                            # Partner already busy in this block — skip this candidate
                            continue
                        pending = _pending_tutorials(partner_sec)
                        if len(pending) >= 2:
                            # Best case: 2 different tutorials for s1 and s2
                            t1, t2 = pending[0], pending[1]
                            p1 = pick_professor(t1, day, s1)
                            p2 = pick_professor(t2, day, s2)
                            if p1 and p2:
                                partner_tuts = [(t1, p1, s1), (t2, p2, s2)]
                            elif p1:
                                # t2 prof unavailable — repeat t1 in s2 as fallback
                                p2 = pick_professor(t1, day, s2)
                                if p2:
                                    partner_tuts = [(t1, p1, s1), (t1, p2, s2)]
                                else:
                                    partner_tuts = [(t1, p1, s1)]
                        if not partner_tuts and len(pending) >= 1:
                            # Only 1 tutorial subject pending — place same subject in BOTH s1 and s2
                            # so the partner stays occupied the full 2-slot lab duration
                            t1 = pending[0]
                            p1 = pick_professor(t1, day, s1)
                            p2 = pick_professor(t1, day, s2)
                            if p1 and p2:
                                partner_tuts = [(t1, p1, s1), (t1, p2, s2)]
                            elif p1:
                                partner_tuts = [(t1, p1, s1)]
                        # If no tutorials pending at all, lab still proceeds

                    prof = pick_professor(ls, day, s1, s2, slot_type='lab')
                    if not prof:
                        continue

                    # Pinned lab room
                    if ls.lab_room:
                        if is_room_free(ls.lab_room.id, day, s1, 2):
                            lab_room = ls.lab_room
                        else:
                            continue
                    else:
                        lab_room = get_free_room(dept_labs, day, s1, slots_needed=2,
                                                  subject_name=ls.name, subject_code=ls.code)

                    # Place lab slots
                    TimeSlot.objects.create(day=day, slot=s1, subject=ls,
                                            professor=prof, section=sec, room=lab_room)
                    TimeSlot.objects.create(day=day, slot=s2, subject=ls,
                                            professor=prof, section=sec, room=lab_room)
                    mark_prof_busy(prof.id, day, s1, slot_mins=100)
                    mark_prof_busy(prof.id, day, s2, slot_mins=0)
                    sec_lab_days_used.add(day)
                    if lab_room:
                        mark_room_busy(lab_room, day, s1, 2)
                    else:
                        no_room_warn.append(f"No lab room for {ls.name} ({sec})")
                    total_created += 2

                    # ── Place partner tutorials simultaneously ─────────────────
                    for (tsubj, tprof, tslot) in partner_tuts:
                        troom = get_free_room(dept_classrooms, day, tslot,
                                              min_capacity=partner_sec.class_count or 0)
                        TimeSlot.objects.create(day=day, slot=tslot, subject=tsubj,
                                                professor=tprof, section=partner_sec, room=troom)
                        mark_prof_busy(tprof.id, day, tslot, slot_mins=50)  # tutorial = 50 min
                        if troom:
                            mark_room_busy(troom, day, tslot)
                        total_created += 1

                    placed = True
                    break

                if not placed:
                    clash_warnings.append(
                        f"{ls.name} ({sec}) — no available lab slot "
                        f"(professor may be at workload limit or room unavailable)"
                    )
        # ── TUTORIAL SCHEDULING ────────────────────────────────────────────────
        # Tutorials that were already placed alongside a partner lab are skipped.
        for sec in sections_in_pair:
            tut_subjs = tutorial_subjects_by_section.get(sec.id, [])
            if not tut_subjs:
                continue
            tut_pool = [ts for ts in tut_subjs for _ in range(ts.lectures_per_week)]
            random.shuffle(tut_pool)
            sec_tut_days_used: set = set()

            for tsubj in tut_pool:
                # Skip if already placed during lab partner-sync above
                already_placed = TimeSlot.objects.filter(
                    section=sec, subject=tsubj, subject__subject_type='TUTORIAL'
                ).count()
                needed = tsubj.lectures_per_week
                if already_placed >= needed:
                    continue  # fully covered by lab partner-sync

                candidates = []
                for day in w_days:
                    if day in sec_tut_days_used:
                        continue
                    if sec.free_day and day == sec.free_day:
                        continue
                    sec_used = set(pair_used_slots[day])
                    for ts_obj in TimeSlot.objects.filter(section=sec, day=day):
                        sec_used.add(ts_obj.slot)
                    for s in avail_slots:
                        if s not in sec_used:
                            candidates.append((day, s))
                # Sort: slot asc across full day (no pre-lunch bias)
                candidates.sort(key=lambda x: x[1])
                placed = False

                for day, s in candidates:
                    sec_used = {ts.slot for ts in TimeSlot.objects.filter(section=sec, day=day)}
                    if s in sec_used or s in pair_used_slots[day]:
                        continue
                    prof = pick_professor(tsubj, day, s)
                    if not prof:
                        continue
                    cls_room = get_free_room(dept_classrooms, day, s,
                                             min_capacity=sec.class_count or 0)
                    TimeSlot.objects.create(day=day, slot=s, subject=tsubj,
                                            professor=prof, section=sec, room=cls_room)
                    mark_prof_busy(prof.id, day, s)
                    if cls_room:
                        mark_room_busy(cls_room, day, s)
                    total_created += 1
                    sec_tut_days_used.add(day)
                    placed = True
                    break

                if not placed:
                    clash_warnings.append(f"Tutorial {tsubj.name} ({sec}) — no free slot")

    # ── G1 / G2 Professor Sync Pass ─────────────────────────────────────────────
    # THEORY/NPTEL: G1 and G2 attend the same physical lecture → must have same professor.
    # LAB/TUTORIAL: separate sessions → each section keeps its own independently assigned prof.
    for pair_key, sections_in_pair in pair_map.items():
        g1_sections = [s for s in sections_in_pair if s.group == 'G1']
        g2_sections = [s for s in sections_in_pair if s.group == 'G2']
        if not g1_sections or not g2_sections:
            continue
        g1_sec = g1_sections[0]
        g2_sec = g2_sections[0]

        # Build map: subject_name -> professor_id from G1 THEORY/NPTEL only
        g1_prof_map = {}
        for ts_obj in TimeSlot.objects.filter(section=g1_sec).select_related('subject'):
            if ts_obj.subject.subject_type in ('THEORY', 'NPTEL'):
                g1_prof_map[ts_obj.subject.name] = ts_obj.professor_id

        # Apply only to G2 THEORY/NPTEL timeslots
        g2_ts_qs = TimeSlot.objects.filter(section=g2_sec).select_related('subject')
        for ts_obj in g2_ts_qs:
            if ts_obj.subject.subject_type not in ('THEORY', 'NPTEL'):
                continue   # labs and tutorials keep their own professor
            matched_prof_id = g1_prof_map.get(ts_obj.subject.name)
            if matched_prof_id and ts_obj.professor_id != matched_prof_id:
                ts_obj.professor_id = matched_prof_id
                ts_obj.save()

    # ── Sync Subject.professors M2M → match actual TimeSlot.professor ─────────
    # Workload report reads Subject.professors (set during CSV import).
    # After generation + sync pass above, ensure the M2M reflects the real
    # professor so that workload report == individual professor timetable.
    for ts_obj in TimeSlot.objects.select_related('subject', 'professor').all():
        if ts_obj.professor and ts_obj.subject:
            ts_obj.subject.professors.set([ts_obj.professor])

    # ── Workload summary ───────────────────────────────────────────────────────
    workload_warnings = []
    for prof in Professor.objects.all():
        hours = professor_mins.get(prof.id, 0) // 60
        if hours > prof.max_workload_hours_per_week:
            workload_warnings.append(
                f"⚠️ {prof.name} assigned {hours}h but limit is {prof.max_workload_hours_per_week}h/week"
            )

    # ── Flash messages ─────────────────────────────────────────────────────────
    messages.success(request, f'✅ Timetable generated! {total_created} time slots created.')
    for w in clash_warnings[:5]:
        messages.warning(request, f'⚠️ {w}')
    for w in no_room_warn[:3]:
        messages.warning(request, f'🚪 {w}')
    for w in workload_warnings[:3]:
        messages.warning(request, w)
    if skipped:
        messages.info(request, f'ℹ️ Skipped {len(skipped)} subject(s) with no professors.')
    if len(clash_warnings) > 5:
        messages.warning(request, f'...and {len(clash_warnings) - 5} more scheduling warnings.')

    return redirect('dashboard')


# ── Department Settings CRUD ───────────────────────────────────────────────────

def dept_settings(request, dept_id):
    """Edit department settings (lunch time, working days, lecture duration)."""
    from .forms import DepartmentSettingsForm
    dept = get_object_or_404(Department, id=dept_id)
    try:
        instance = dept.settings
    except DepartmentSettings.DoesNotExist:
        instance = None
    form = DepartmentSettingsForm(request.POST or None, instance=instance)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.department = dept
        # End slot always = start slot (single-slot lunch, end slot removed from UI)
        obj.lunch_end_slot = obj.lunch_start_slot
        obj.save()
        messages.success(request, f'✅ Settings saved for {dept.name}.')
        return redirect('dashboard')
    return render(request, 'dept_settings_form.html', {
        'form': form, 'dept': dept, 'title': f'Settings — {dept.name}', 'icon': '⚙️'
    })


# ── CSV Export ─────────────────────────────────────────────────────────────────

def export_timetable_csv(request, section_id):
    """Export section timetable as CSV."""
    import csv as csv_module
    section = get_object_or_404(Section, id=section_id)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="timetable_{section_id}.csv"'
    writer = csv_module.writer(response)
    writer.writerow(['Day', 'Slot', 'Time', 'Subject', 'Type', 'Professor', 'Room'])
    for ts in TimeSlot.objects.filter(section=section).select_related(
        'subject', 'professor', 'room'
    ).order_by('day', 'slot'):
        writer.writerow([
            ts.day, ts.slot, SLOT_TIMES_DISPLAY.get(ts.slot, ''),
            ts.subject.name, ts.subject.get_subject_type_display(),
            ts.professor.name, ts.room.name if ts.room else '—',
        ])
    return response


def export_professor_csv(request, professor_id):
    """Export professor schedule as CSV."""
    import csv as csv_module
    professor = get_object_or_404(Professor, id=professor_id)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="prof_schedule_{professor_id}.csv"'
    writer = csv_module.writer(response)
    writer.writerow(['Day', 'Slot', 'Time', 'Subject', 'Section', 'Room'])
    for ts in TimeSlot.objects.filter(professor=professor).select_related(
        'subject', 'section', 'room'
    ).order_by('day', 'slot'):
        writer.writerow([
            ts.day, ts.slot, SLOT_TIMES_DISPLAY.get(ts.slot, ''),
            ts.subject.name,
            str(ts.section) if ts.section else '—',
            ts.room.name if ts.room else '—',
        ])
    return response


def export_room_csv(request, room_id):
    """Export room occupancy as CSV."""
    import csv as csv_module
    room = get_object_or_404(Room, id=room_id)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="room_schedule_{room_id}.csv"'
    writer = csv_module.writer(response)
    writer.writerow(['Day', 'Slot', 'Time', 'Subject', 'Professor', 'Section'])
    for ts in TimeSlot.objects.filter(room=room).select_related(
        'subject', 'professor', 'section'
    ).order_by('day', 'slot'):
        writer.writerow([
            ts.day, ts.slot, SLOT_TIMES_DISPLAY.get(ts.slot, ''),
            ts.subject.name, ts.professor.name,
            str(ts.section) if ts.section else '—',
        ])
    return response


# ── Combine Edit ───────────────────────────────────────────────────────────────

def combine_edit(request):
    """
    Combine Edit page — shows every timetable slot with all related data in one
    editable table.  Editable fields: professor, subject name/code, L/T/P.
    Room / day / slot are read-only here (edit via individual timetable view).
    Changes auto-save and sync to timetable, workload and schedule views.
    """
    timeslots = (
        TimeSlot.objects
        .select_related('subject__section__course__department', 'professor', 'section')
        .order_by('section__course__department__name', 'section__course__name',
                  'section__year', 'section__group', 'day', 'slot')
    )
    professors = Professor.objects.all().order_by('name')

    return render(request, 'combine_edit.html', {
        'timeslots':  timeslots,
        'professors': professors,
    })


import json as _json

def combine_edit_save(request):
    """
    AJAX endpoint for Combine Edit.
    Editable fields: professor, subject_name, subject_code, lectures, tutorials, practicals.
    Room / day / slot are NOT changed here (they are not exposed in the Combine Edit UI).

    Payload: list of { id, professor_id, subject_name, subject_code,
                       lectures, tutorials, practicals }

    Validation:
      - Professor workload limit check (warning, not hard error)
      - Subject name must not be blank
    """
    from django.http import JsonResponse
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    try:
        payload = _json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Bad JSON'}, status=400)

    errors   = []
    warnings = []

    # Pre-load timeslots
    ts_ids = [row.get('id') for row in payload if row.get('id')]
    ts_map = {ts.id: ts for ts in TimeSlot.objects.select_related(
        'subject', 'professor').filter(id__in=ts_ids)}

    # Stage changes & validate
    staged = []
    for row in payload:
        ts_id = row.get('id')
        if not ts_id or ts_id not in ts_map:
            errors.append(f"Unknown slot id {ts_id}")
            continue

        ts      = ts_map[ts_id]
        prof_id = int(row.get('professor_id', ts.professor_id))

        # Validate subject name not blank
        subj_name = (row.get('subject_name') or '').strip()
        if not subj_name:
            errors.append(f"Row {ts_id}: Subject name cannot be empty.")
            continue

        staged.append((ts, prof_id, row))

    if errors:
        return JsonResponse({'ok': False, 'errors': errors, 'warnings': warnings})

    # Workload check (per professor across all staged rows)
    from collections import defaultdict
    prof_ltp = defaultdict(int)  # prof_id -> total L+T+P after changes
    for ts, prof_id, row in staged:
        l = int(row.get('lectures',   ts.subject.lectures_per_week) or 0)
        t = int(row.get('tutorials',  0) or 0)
        p = int(row.get('practicals', 0) or 0)
        prof_ltp[prof_id] += l + t + p

    # Compare against DB limit
    prof_ids  = list(prof_ltp.keys())
    prof_objs = {p.id: p for p in Professor.objects.filter(id__in=prof_ids)}
    for pid, total in prof_ltp.items():
        prof = prof_objs.get(pid)
        if prof and prof.max_workload_hours_per_week > 0:
            if total > prof.max_workload_hours_per_week:
                warnings.append(
                    f"⚠️ {prof.name} has {total} hrs/wk — exceeds limit of "
                    f"{prof.max_workload_hours_per_week} hrs/wk."
                )

    # Apply changes
    for ts, prof_id, row in staged:
        ts.professor_id = prof_id

        subj = ts.subject
        subj_name = (row.get('subject_name') or '').strip()
        if subj_name:
            subj.name = subj_name
        subj_code = (row.get('subject_code') or '').strip()
        subj.code = subj_code   # allow clearing the code

        lec  = int(row.get('lectures',  0) or 0)
        tut  = int(row.get('tutorials', 0) or 0)
        prac = int(row.get('practicals',0) or 0)

        # Determine dominant field and update subject_type + lectures_per_week
        if prac > 0:
            subj.subject_type     = 'LAB'
            subj.lectures_per_week = prac
            subj.duration          = 2
        elif tut > 0:
            subj.subject_type     = 'TUTORIAL'
            subj.lectures_per_week = tut
            subj.duration          = 1
        elif lec > 0:
            # Keep existing NPTEL if already set, otherwise THEORY
            if subj.subject_type not in ('NPTEL',):
                subj.subject_type = 'THEORY'
            subj.lectures_per_week = lec
            subj.duration          = 1
        # else: all zero — don't change type, just update count to 0
        if lec == 0 and tut == 0 and prac == 0:
            subj.lectures_per_week = 0

        subj.save()
        ts.save()

        # ── Sync professor to sibling group (G1 <-> G2 same section) ──────────
        # Rule: Sec A G1 aur Sec A G2 ka same subject → same professor hona chahiye
        # THEORY: same day+slot  |  TUTORIAL/LAB: different slots → match by name only
        if ts.section:
            sec = ts.section
            sibling_group = 'G2' if sec.group == 'G1' else 'G1'

            sib_base = TimeSlot.objects.filter(
                subject__name=subj.name,
                section__course_id=sec.course_id,
                section__year=sec.year,
                section__section_name=sec.section_name,
                section__group=sibling_group,
            ).select_related('subject')

            if subj.subject_type == 'THEORY':
                sibling_ts_qs = sib_base.filter(day=ts.day, slot=ts.slot)
            else:
                sibling_ts_qs = sib_base

            for sib_ts in sibling_ts_qs:
                sib_ts.professor_id = prof_id
                sib_ts.save()
                sib_subj = sib_ts.subject
                if subj_name:
                    sib_subj.name = subj_name
                sib_subj.code              = subj_code
                sib_subj.subject_type      = subj.subject_type
                sib_subj.lectures_per_week = subj.lectures_per_week
                sib_subj.duration          = subj.duration
                sib_subj.save()

    # Compute updated per-professor workload totals to return to frontend
    # Include sibling profs too so their workload pills update in UI
    staged_prof_ids = {prof_id for ts, prof_id, row in staged}
    sibling_prof_ids = set()
    for ts, prof_id, row in staged:
        if ts.section:
            sec = ts.section
            sib_group = 'G2' if sec.group == 'G1' else 'G1'
            sib_ts_list = TimeSlot.objects.filter(
                section__course_id=sec.course_id,
                section__year=sec.year,
                section__section_name=sec.section_name,
                section__group=sib_group,
            ).values_list('professor_id', flat=True)
            sibling_prof_ids.update(sib_ts_list)
    prof_ids_affected = list(staged_prof_ids | sibling_prof_ids)
    wl_totals = {}
    for pid in prof_ids_affected:
        total = 0
        for ts in TimeSlot.objects.filter(professor_id=pid).select_related('subject'):
            n  = ts.subject.lectures_per_week
            total += n  # L+T+P already encoded in lectures_per_week per type
        wl_totals[str(pid)] = total

    return JsonResponse({
        'ok': True,
        'saved': len(staged),
        'warnings': warnings,
        'workload_totals': wl_totals,   # { prof_id: total_hrs }
    })


def combine_edit_export_csv(request):
    """Export workload CSV — Faculty Name, Subject, Code, Class-Sem, L, T, P, Group, Total."""
    import csv as csv_module
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="workload_report.csv"'
    response.write('\ufeff')  # UTF-8 BOM for Excel
    writer = csv_module.writer(response)
    writer.writerow([
        'Department', 'Faculty Name', 'Subject Name', 'Subject Code',
        'Class-Sem', 'Group', 'L', 'T', 'P', 'Total',
    ])
    timeslots = (
        TimeSlot.objects
        .select_related('subject__section__course__department', 'professor', 'section')
        .order_by('section__course__department__name',
                  'professor__name', 'section__course__name')
    )
    for ts in timeslots:
        sec   = ts.section
        subj  = ts.subject
        stype = subj.subject_type
        n     = subj.lectures_per_week
        l_val = n if stype in ('THEORY', 'NPTEL') else 0
        t_val = n if stype == 'TUTORIAL' else 0
        p_val = n if stype == 'LAB' else 0
        dept_name  = sec.course.department.name if sec else ''
        year_label = sec.get_year_display_label() if sec else ''
        sem_label  = f"{sec.course.get_display_name()} {year_label}" if sec else ''
        writer.writerow([
            dept_name,
            ts.professor.name,
            subj.name,
            subj.code or '',
            sem_label,
            sec.group if sec else '',
            l_val, t_val, p_val,
            l_val + t_val + p_val,
        ])
    return response


# ── Workload Report ────────────────────────────────────────────────────────────

def workload_report(request):
    """
    Formatted workload report — Amritsar College workload sheet format.
    Groups: department -> professor -> subjects, with per-prof & per-dept totals.
    Supports ?dept= filter. Printable as PDF.
    """
    from collections import defaultdict, OrderedDict
    from datetime import date

    dept_filter_id = request.GET.get('dept')
    departments    = Department.objects.all().order_by('name')

    def mins_to_display(slots):
        """Convert contact slots to display. Each slot = 1 contact hr.
        Theory/Tutorial = 1 slot each, Lab = 2 slots."""
        if slots == 0:
            return '—'
        return f'{slots} hrs'

    # FIX: Query Subject directly so lectures_per_week counted ONCE per subject,
    # not once per generated timeslot — this matches the professor schedule page.
    subj_qs = (
        Subject.objects
        .select_related('section__course__department', 'section')
        .prefetch_related('professors')
        .order_by('section__course__department__name',
                  'section__course__name',
                  'section__year', 'section__group')
    )
    if dept_filter_id:
        subj_qs = subj_qs.filter(section__course__department_id=dept_filter_id)

    # dept_name -> { prof_id -> { name, max, rows:[], l, t, p, total } }
    dept_profs  = defaultdict(OrderedDict)
    dept_totals = defaultdict(lambda: {'l':0,'t':0,'p':0,'total':0})

    # THEORY / NPTEL de-duplication set:
    # key = (prof_id, subject_name, section_name, year, course_id)
    # Prevents counting the same shared lecture twice (once for G1, once for G2)
    theory_counted = set()

    for subj in subj_qs:
        sec   = subj.section
        if not sec:
            continue
        stype = subj.subject_type
        n     = subj.lectures_per_week
        l_val = n if stype in ('THEORY', 'NPTEL') else 0
        t_val = n if stype == 'TUTORIAL' else 0
        p_val = n if stype == 'LAB' else 0

        dept_name  = sec.course.department.name
        year_label = sec.get_year_display_label()
        sem_label  = f"{sec.course.get_display_name()} {year_label}"

        for prof in subj.professors.all():
            pid = prof.id

            # ── THEORY / NPTEL shared-lecture dedup ──────────────────────────
            # G1 and G2 attend the SAME physical lecture → count hours ONCE.
            # But show the row as "G1 & G2" so it's clear both groups are covered.
            # G2 row is completely skipped; G1 row is updated to say "G1 & G2".
            dedup_key = (pid, subj.name, sec.section_name, sec.year, sec.course_id)
            if stype in ('THEORY', 'NPTEL'):
                if sec.group == 'G2':
                    # G2 — check if G1 row already added for this prof+subject+section
                    if dedup_key in theory_counted:
                        # G1 row exists — update its group label to "G1 & G2"
                        if pid in dept_profs.get(dept_name, {}):
                            for row in dept_profs[dept_name][pid]['rows']:
                                if (row['subject'] == subj.name
                                        and row.get('_sec_name') == sec.section_name
                                        and row.get('group') == 'G1'):
                                    row['group'] = 'G1 & G2'
                                    break
                        continue  # Don't add G2 as separate row or add extra hours
                elif sec.group == 'G1':
                    theory_counted.add(dedup_key)  # Record so G2 merges into this

            if pid not in dept_profs[dept_name]:
                dept_profs[dept_name][pid] = {
                    'name': prof.name,
                    'max':  prof.max_workload_hours_per_week,
                    'rows': [], 'l':0, 't':0, 'p':0, 'total':0,
                }
            pe = dept_profs[dept_name][pid]
            row_mins = l_val*1 + t_val*1 + p_val*2   # contact slots: theory/tut=1, lab=2
            pe['rows'].append({
                'subject':      subj.name,
                'code':         subj.code or '',
                'class_sem':    sem_label,
                'group':        sec.group,
                '_sec_name':    sec.section_name,   # internal — for G2 merge lookup
                'l': l_val, 't': t_val, 'p': p_val,
                'total':        l_val + t_val + p_val,
                'time_display': mins_to_display(row_mins),
            })
            pe['l']     += l_val
            pe['t']     += t_val
            pe['p']     += p_val
            pe['total'] += l_val + t_val + p_val
            pe['mins']  = pe.get('mins', 0) + row_mins

            dt = dept_totals[dept_name]
            dt['l']     += l_val
            dt['t']     += t_val
            dt['p']     += p_val
            dt['total'] += l_val + t_val + p_val

    # Add time_display to each prof entry
    for dept_name, prof_map in dept_profs.items():
        dept_mins = 0
        for pid, pe in prof_map.items():
            pe['time_display'] = mins_to_display(pe.get('mins', 0))
            dept_mins += pe.get('mins', 0)
        dept_totals[dept_name]['time_display'] = mins_to_display(dept_mins)

    today = date.today()
    # Try to get semester dates from DepartmentSettings
    # Fall back to auto-detecting from current month
    try:
        from .models import DepartmentSettings
        ds = DepartmentSettings.objects.first()
        # DeptSettings has working_days etc but no explicit semester dates
        # Use current month heuristic — Jan–Jun = Odd sem, Jul–Dec = Even sem
    except Exception:
        ds = None
    if today.month <= 6:
        sem_period = f"Jan,{today.year}–Jun,{today.year}"
    else:
        sem_period = f"Jul,{today.year}–Dec,{today.year}"

    selected_dept = None
    if dept_filter_id:
        try:
            selected_dept = Department.objects.get(id=dept_filter_id)
        except Department.DoesNotExist:
            pass

    grand = {'l':0,'t':0,'p':0,'total':0}
    for dt in dept_totals.values():
        grand['l']     += dt['l']
        grand['t']     += dt['t']
        grand['p']     += dt['p']
        grand['total'] += dt['total']

    return render(request, 'workload_report.html', {
        'dept_profs':    dict(dept_profs),    # dept -> OrderedDict(prof_id -> prof_entry)
        'dept_totals':   dict(dept_totals),
        'departments':   departments,
        'selected_dept': selected_dept,
        'dept_filter_id':dept_filter_id,
        'sem_period':    sem_period,
        'today':         today,
        'grand_total':   grand,
    })


def workload_report_csv(request):
    """Export workload report as CSV — optionally filtered by ?dept=id."""
    import csv as csv_module
    from collections import OrderedDict

    dept_filter_id = request.GET.get('dept')
    filename = 'workload_report_all.csv'
    if dept_filter_id:
        try:
            dept_obj = Department.objects.get(id=dept_filter_id)
            filename = f'workload_{dept_obj.name.replace(" ","_")}.csv'
        except Department.DoesNotExist:
            pass

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')  # UTF-8 BOM for Excel
    writer = csv_module.writer(response)
    writer.writerow(['Department','Faculty Name','Subject Name','Subject Code',
                     'Class-Sem','Group','L','T','P','Total',
                     'Prof Max hrs/wk','Status'])

    # FIX: Use Subject (not TimeSlot) so lectures_per_week counted once per subject
    subj_qs = (
        Subject.objects
        .select_related('section__course__department', 'section')
        .prefetch_related('professors')
        .order_by('section__course__department__name',
                  'section__course__name', 'section__year', 'section__group')
    )
    if dept_filter_id:
        subj_qs = subj_qs.filter(section__course__department_id=dept_filter_id)

    from collections import defaultdict
    prof_totals = defaultdict(int)
    prof_max    = {}
    rows_list   = []
    for subj in subj_qs:
        sec   = subj.section
        if not sec:
            continue
        stype = subj.subject_type
        n     = subj.lectures_per_week
        l_v   = n if stype in ('THEORY','NPTEL') else 0
        t_v   = n if stype == 'TUTORIAL' else 0
        p_v   = n if stype == 'LAB' else 0
        for prof in subj.professors.all():
            pid = prof.id
            prof_totals[pid] += l_v + t_v + p_v
            prof_max[pid]     = prof.max_workload_hours_per_week
            rows_list.append({
                'dept':  sec.course.department.name,
                'prof':  prof.name,
                'subj':  subj.name,
                'code':  subj.code or '',
                'sem':   f"{sec.course.get_display_name()} {sec.get_year_display_label()}",
                'grp':   sec.group,
                'l': l_v, 't': t_v, 'p': p_v,
                'total': l_v + t_v + p_v,
                'pid':   pid,
            })

    for r in rows_list:
        pid = r['pid']
        mx  = prof_max.get(pid, 0)
        tot = prof_totals[pid]
        if tot == 0:
            status = 'No load'
        elif mx > 0 and tot > mx:
            status = f'Over limit ({tot}/{mx})'
        elif mx > 0 and tot >= mx - 2:
            status = f'Near limit ({tot}/{mx})'
        else:
            status = 'OK'

        writer.writerow([r['dept'],r['prof'],r['subj'],r['code'],r['sem'],r['grp'],
                         r['l'],r['t'],r['p'],r['total'],mx or '',status])
    return response


# ─────────────────────────────────────────────────────────────────────────────
# FREE ROOMS & LABS MODULE  (add-on — does not modify any existing view)
# ─────────────────────────────────────────────────────────────────────────────
from django.http import HttpResponse as _HttpResponse
import io as _io

def free_rooms(request):
    """
    Add-on view: show which rooms/labs are completely free on each day/slot.
    Reads existing TimeSlot + RoomOccupiedTime data — never writes anything.
    """
    from .models import Room, TimeSlot, RoomOccupiedTime, SLOT_TIMES_DISPLAY, DAY_CHOICES

    ALL_DAYS  = [d[0] for d in DAY_CHOICES]           # Mon-Fri
    ALL_SLOTS = sorted(SLOT_TIMES_DISPLAY.keys())      # 1-7

    filter_day  = request.GET.get('day',  '').strip()
    filter_slot = request.GET.get('slot', '').strip()
    filter_type = request.GET.get('type', '').strip()   # CLASSROOM / LAB / ''

    days_to_show  = [filter_day]  if filter_day  else ALL_DAYS
    slots_to_show = [int(filter_slot)] if filter_slot else ALL_SLOTS

    # Build occupied sets
    # occupied_by_timetable[room_id][day] = {slot, ...}
    from collections import defaultdict
    occ_tt  = defaultdict(lambda: defaultdict(set))
    occ_man = defaultdict(lambda: defaultdict(set))

    for ts in TimeSlot.objects.select_related('room').filter(room__isnull=False):
        occ_tt[ts.room_id][ts.day].add(ts.slot)

    for rot in RoomOccupiedTime.objects.select_related('room'):
        for s in rot.blocked_slots():
            occ_man[rot.room_id][rot.day].add(s)

    rooms_qs = Room.objects.all().order_by('room_type', 'name')
    if filter_type:
        rooms_qs = rooms_qs.filter(room_type=filter_type)

    # Build result rows: one row per (room, day, consecutive-free-block)
    rows = []
    for room in rooms_qs:
        for day in days_to_show:
            free_slots = []
            for slot in slots_to_show:
                busy = (slot in occ_tt[room.id][day]) or (slot in occ_man[room.id][day])
                if not busy:
                    free_slots.append(slot)
            if free_slots:
                # Group consecutive slots into ranges for readability
                def group_consecutive(nums):
                    groups, cur = [], []
                    for n in sorted(nums):
                        if not cur or n == cur[-1] + 1:
                            cur.append(n)
                        else:
                            groups.append(cur)
                            cur = [n]
                    if cur:
                        groups.append(cur)
                    return groups

                ranges = []
                for grp in group_consecutive(free_slots):
                    if len(grp) == 1:
                        ranges.append(SLOT_TIMES_DISPLAY[grp[0]])
                    else:
                        ranges.append(f"{SLOT_TIMES_DISPLAY[grp[0]]} – {SLOT_TIMES_DISPLAY[grp[-1]]}")

                rows.append({
                    'room_name': room.name,
                    'room_type': room.get_room_type_display(),
                    'capacity':  room.capacity,
                    'day':       day,
                    'free_slots_raw': free_slots,
                    'free_slots_display': ', '.join(ranges),
                    'count': len(free_slots),
                })

    context = {
        'rows':          rows,
        'all_days':      ALL_DAYS,
        'all_slots':     ALL_SLOTS,
        'slot_display':  SLOT_TIMES_DISPLAY,
        'filter_day':    filter_day,
        'filter_slot':   filter_slot,
        'filter_type':   filter_type,
        'total_free':    sum(r['count'] for r in rows),
    }
    return render(request, 'free_rooms.html', context)



def free_students(request):
    """
    Dean view: show which sections have FREE students at a given Dept + Day + Slot.
    A section is "free" if no TimeSlot exists for it on that day+slot.
    Uses class_count from Section model for student count.
    """
    from .models import Section, TimeSlot, Department, SLOT_TIMES_DISPLAY, DAY_CHOICES

    ALL_DAYS  = [d[0] for d in DAY_CHOICES]
    ALL_SLOTS = sorted(SLOT_TIMES_DISPLAY.keys())

    filter_dept = request.GET.get('dept',  '').strip()
    filter_day  = request.GET.get('day',   '').strip()
    filter_slot = request.GET.get('slot',  '').strip()

    departments = Department.objects.all().order_by('name')

    # Build busy set: section_id -> {(day, slot)}
    busy = defaultdict(set)
    for ts in TimeSlot.objects.values_list('section_id', 'day', 'slot'):
        busy[ts[0]].add((ts[1], ts[2]))

    # Filter sections
    sections_qs = Section.objects.select_related('course__department').all()
    if filter_dept:
        sections_qs = sections_qs.filter(course__department__name=filter_dept)

    days_to_check  = [filter_day]        if filter_day  else ALL_DAYS
    slots_to_check = [int(filter_slot)]  if filter_slot else ALL_SLOTS

    # Build results grouped by dept → day → slot → list of free sections
    results = []   # list of dicts for template

    for day in days_to_check:
        for slot in slots_to_check:
            free_sections = []
            for sec in sections_qs:
                # Skip lunch slot for this dept
                if (day, slot) in busy[sec.id]:
                    continue   # section is busy
                dept_name    = sec.course.department.name
                course_name  = sec.course.get_display_name() if hasattr(sec.course, 'get_display_name') else sec.course.name
                free_sections.append({
                    'dept':         dept_name,
                    'course':       course_name,
                    'year':         sec.year,
                    'section':      sec.section_name,
                    'group':        sec.group,
                    'class_count':  sec.class_count if sec.class_count else 0,
                    'section_label': f"{course_name} {sec.year} Yr · Sec {sec.section_name} {sec.group}",
                })

            if free_sections:
                # Group by dept
                dept_groups = defaultdict(list)
                for s in free_sections:
                    dept_groups[s['dept']].append(s)

                for dept_name, secs in sorted(dept_groups.items()):
                    total_students = sum(s['class_count'] for s in secs)
                    has_counts = any(s['class_count'] > 0 for s in secs)
                    results.append({
                        'day':            day,
                        'slot':           slot,
                        'slot_display':   SLOT_TIMES_DISPLAY.get(slot, str(slot)),
                        'dept':           dept_name,
                        'sections':       secs,
                        'total_students': total_students,
                        'has_counts':     has_counts,
                        'section_count':  len(secs),
                    })

    # Grand total free students across all results
    grand_total = sum(r['total_students'] for r in results)

    context = {
        'results':      results,
        'departments':  departments,
        'all_days':     ALL_DAYS,
        'all_slots':    ALL_SLOTS,
        'slot_display': SLOT_TIMES_DISPLAY,
        'filter_dept':  filter_dept,
        'filter_day':   filter_day,
        'filter_slot':  filter_slot,
        # Pass as int so slot_display|get_item:filter_slot_int works with int-keyed dict
        'filter_slot_int': int(filter_slot) if filter_slot else None,
        'grand_total':  grand_total,
    }
    return render(request, 'free_students.html', context)

def free_rooms_pdf(request):
    """Export the free-rooms table as a PDF (add-on — no existing code touched)."""
    from .models import Room, TimeSlot, RoomOccupiedTime, SLOT_TIMES_DISPLAY, DAY_CHOICES
    from collections import defaultdict
    import datetime

    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
    except ImportError:
        return _HttpResponse("reportlab not installed. Run: pip install reportlab", status=500)

    ALL_DAYS  = [d[0] for d in DAY_CHOICES]
    ALL_SLOTS = sorted(SLOT_TIMES_DISPLAY.keys())

    filter_day  = request.GET.get('day',  '').strip()
    filter_slot = request.GET.get('slot', '').strip()
    filter_type = request.GET.get('type', '').strip()

    days_to_show  = [filter_day]  if filter_day  else ALL_DAYS
    slots_to_show = [int(filter_slot)] if filter_slot else ALL_SLOTS

    occ_tt  = defaultdict(lambda: defaultdict(set))
    occ_man = defaultdict(lambda: defaultdict(set))
    for ts in TimeSlot.objects.select_related('room').filter(room__isnull=False):
        occ_tt[ts.room_id][ts.day].add(ts.slot)
    for rot in RoomOccupiedTime.objects.select_related('room'):
        for s in rot.blocked_slots():
            occ_man[rot.room_id][rot.day].add(s)

    rooms_qs = Room.objects.all().order_by('room_type', 'name')
    if filter_type:
        rooms_qs = rooms_qs.filter(room_type=filter_type)

    rows = []
    for room in rooms_qs:
        for day in days_to_show:
            free_slots = []
            for slot in slots_to_show:
                if slot not in occ_tt[room.id][day] and slot not in occ_man[room.id][day]:
                    free_slots.append(slot)
            if free_slots:
                def group_consecutive(nums):
                    groups, cur = [], []
                    for n in sorted(nums):
                        if not cur or n == cur[-1] + 1:
                            cur.append(n)
                        else:
                            groups.append(cur)
                            cur = [n]
                    if cur:
                        groups.append(cur)
                    return groups

                ranges = []
                for grp in group_consecutive(free_slots):
                    if len(grp) == 1:
                        ranges.append(SLOT_TIMES_DISPLAY[grp[0]])
                    else:
                        ranges.append(f"{SLOT_TIMES_DISPLAY[grp[0]]} – {SLOT_TIMES_DISPLAY[grp[-1]]}")
                rows.append([room.name, room.get_room_type_display(), str(room.capacity), day,
                             ', '.join(ranges), str(len(free_slots))])

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    blue = colors.HexColor('#1565c0')
    green = colors.HexColor('#16a34a')

    elems = []
    title_style = ParagraphStyle('Title', parent=styles['Title'],
                                 fontSize=18, textColor=blue, spaceAfter=6)
    sub_style = ParagraphStyle('Sub', parent=styles['Normal'],
                               fontSize=10, textColor=colors.grey, spaceAfter=14)
    elems.append(Paragraph("Free Rooms & Labs Report", title_style))
    now = datetime.datetime.now().strftime('%d %b %Y, %I:%M %p')
    filters = []
    if filter_day:  filters.append(f"Day: {filter_day}")
    if filter_slot: filters.append(f"Slot: {SLOT_TIMES_DISPLAY.get(int(filter_slot),'')}")
    if filter_type: filters.append(f"Type: {filter_type.title()}")
    sub_txt = f"Generated: {now}" + (f"  |  Filters: {', '.join(filters)}" if filters else "")
    elems.append(Paragraph(sub_txt, sub_style))

    header = ['Room / Lab', 'Type', 'Capacity', 'Day', 'Free Time Slots', '# Free Slots']
    data = [header] + rows if rows else [header, ['No free slots found', '', '', '', '', '']]

    col_widths = [5*cm, 3*cm, 2.5*cm, 3*cm, 11*cm, 3*cm]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), blue),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,0), 10),
        ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
        ('ALIGN',      (0,1), (0,-1), 'LEFT'),
        ('ALIGN',      (4,1), (4,-1), 'LEFT'),
        ('FONTSIZE',   (0,1), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f0f7ff')]),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#d0d7e3')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
    ]))
    elems.append(t)

    doc.build(elems)
    buf.seek(0)
    resp = _HttpResponse(buf, content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="free_rooms_report.pdf"'
    return resp
