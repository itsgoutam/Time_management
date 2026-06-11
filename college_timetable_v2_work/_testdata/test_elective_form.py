import os, sys, django
sys.path.insert(0, 'D:/college_timetable_v2_work')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'college_timetable.settings')
django.setup()
from django.test.runner import DiscoverRunner
from django.test.utils import setup_test_environment, teardown_test_environment
runner = DiscoverRunner(verbosity=0); cfg = runner.setup_databases(); setup_test_environment()
from django.test import Client
from scheduler.models import (Department, DepartmentSettings, Course, Section, Professor,
                              Room, Subject, TimeSlot)
from scheduler.forms import SubjectForm
from scheduler import accounts as acc

P=[]; F=[]
def ck(l,c,extra=''):
    (P if c else F).append(l); print(('  PASS ' if c else '  FAIL ')+l+(f'  [{extra}]' if extra else ''))

acc.seed_default_admin()
a = Client(); a.post('/login/', {'login_type':'admin','username':'admin','password':'admin123'})

d = Department.objects.create(name='CSE')
DepartmentSettings.objects.create(department=d, lunch_start_slot=5, lunch_end_slot=5, dept_start_slot=1)
c = Course.objects.create(department=d, name='BTECH')
for i in range(3): Room.objects.create(name=f'R{i}', room_id=f'R{i}', room_type='CLASSROOM', capacity=120, department=d)
sec = Section.objects.create(course=c, year='6', section_name='A', group='G1', class_count=30)
prof = Professor.objects.create(name='Dr E', professor_id='E1', department=d, max_workload_hours_per_week=40)

print('=== 1. Form offers ELECTIVE option ===')
choices = [x[0] for x in SubjectForm().fields['subject_type'].choices]
ck('ELECTIVE is in the subject-type dropdown', 'ELECTIVE' in choices, str(choices))

print('=== 2. Adding an ELECTIVE subject ===')
r = a.post('/add-subject/', {
    'save_subject': '1', 'code': 'EL1', 'name': 'AI Elective',
    'subject_type': 'ELECTIVE', 'duration': '50', 'lectures_per_week': '2',
    'sections': [sec.id], 'professor': prof.id,
}, follow=True)
ck('add-subject POST ok', r.status_code == 200)
sub = Subject.objects.filter(name='AI Elective').first()
ck('subject created', sub is not None)
if sub:
    ck('stored as 50-min THEORY (valid model type)', sub.subject_type == 'THEORY' and sub.duration == 50,
       f'{sub.subject_type}/{sub.duration}')
    ck('flagged is_elective = True', sub.is_elective is True)

print('=== 3. Edit pre-selects ELECTIVE ===')
f = SubjectForm(instance=sub)
ck('edit form shows ELECTIVE selected', f.fields['subject_type'].initial == 'ELECTIVE',
   str(f.fields['subject_type'].initial))

print('=== 4. Elective shown distinctively in the timetable ===')
# add a couple more electives so they schedule in parallel, then generate
for n in range(2):
    s2 = Subject.objects.create(name=f'Elec{n}', subject_type='THEORY', duration=50,
                                lectures_per_week=2, section=sec, allowed_groups='BOTH', is_elective=True)
    p2 = Professor.objects.create(name=f'P{n}', professor_id=f'P{n}', department=d, max_workload_hours_per_week=40)
    s2.professors.set([p2])
a.get('/generate-smart/', follow=True)
ck('elective timeslots generated', TimeSlot.objects.filter(subject__is_elective=True).exists(),
   str(TimeSlot.objects.filter(subject__is_elective=True).count()))
# section timetable page marks them
html = a.get(f'/timetable/{sec.id}/').content.decode()
ck('section timetable uses the elective style (cell-elec)', 'cell-elec' in html)
ck('section timetable shows the Elective badge', 'Elective' in html)
# professor schedule too
ep = TimeSlot.objects.filter(subject__is_elective=True).first().professor
phtml = a.get(f'/professor/{ep.id}/').content.decode()
ck('professor schedule marks elective (cell-elec)', 'cell-elec' in phtml)

print(f"\nTOTAL: {len(P)} passed, {len(F)} failed")
for x in F: print('  FAIL:', x)
teardown_test_environment(); runner.teardown_databases(cfg)
