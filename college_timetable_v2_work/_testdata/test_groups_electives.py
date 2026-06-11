import os, sys, django
sys.path.insert(0, 'D:/college_timetable_v2_work')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'college_timetable.settings')
django.setup()
from django.test.runner import DiscoverRunner
from django.test.utils import setup_test_environment, teardown_test_environment
runner = DiscoverRunner(verbosity=0); cfg = runner.setup_databases(); setup_test_environment()
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from collections import defaultdict
from scheduler.models import (Department, DepartmentSettings, Course, Section, Professor,
                              Room, Subject, TimeSlot)
from scheduler.forms import SectionForm
from scheduler import accounts as acc

PASS=[]; FAIL=[]
def ck(l,c,extra=''):
    (PASS if c else FAIL).append(l); print(('  PASS ' if c else '  FAIL ')+l+(f'  [{extra}]' if extra else ''))
def sec(t): print('\n=== '+t+' ===')

base='D:/college_timetable_v2_work/_testdata/'
acc.seed_default_admin()
a=Client(); a.post('/login/', {'login_type':'admin','username':'admin','password':'admin123'})
files={f'{k}_csv':SimpleUploadedFile(f'{k}.csv',open(base+f'{k}.csv','rb').read(),content_type='text/csv') for k in ['dept_settings','rooms','professors','sections','subjects']}
a.post('/csv-upload/', dict(files, auto_generate=''), follow=True)

cse=Department.objects.get(name__startswith='Computer')
course=Course.objects.filter(department=cse).first()

sec('1. SECTION dropdown lists CSV section names (I, II, III)')
f = SectionForm()
choice_vals = [c[0] for c in f.fields['section_name'].choices]
print('   section dropdown options:', choice_vals)
ck('dropdown includes CSV custom sections I, II, III', {'I','II','III'} <= set(choice_vals))
ck('dropdown still includes standard A-E', {'A','B','C','D','E'} <= set(choice_vals))
ck('dropdown includes a Custom option', 'CUSTOM' in choice_vals)

sec('2. GROUP button adds groups (add a group to existing section I)')
before = Section.objects.filter(course=course, year='3', section_name='CUSTOM', custom_section_name='I').count()
r = a.post('/add-section/', {
    'course': course.id, 'year': '3',
    'section_name': 'I', 'custom_section_name': '',
    'groups': ['G2','G4'],     # add two new groups to section I
    'section_start_slot': '',
}, follow=True)
ck('add-section POST ok', r.status_code==200)
secI = Section.objects.filter(course=course, year='3', section_name='CUSTOM', custom_section_name='I')
groups_now = sorted(secI.values_list('group', flat=True))
ck('new groups G2, G4 created under Section I', 'G2' in groups_now and 'G4' in groups_now, f'{groups_now}')
ck('Section I stored consistently as CUSTOM + "I" (not duplicated)',
   secI.count()==before+2 and not Section.objects.filter(section_name='I').exists())

# brand-new standard section + multiple groups
a.post('/add-section/', {'course': course.id, 'year': '4', 'section_name': 'A',
                         'custom_section_name': '', 'groups': ['G1','G2'], 'section_start_slot': ''}, follow=True)
newA = Section.objects.filter(course=course, year='4', section_name='A')
ck('new Section A (sem 4) created with G1+G2', sorted(newA.values_list('group',flat=True))==['G1','G2'])

sec('3. ELECTIVES run in PARALLEL (same slot, different rooms)')
# Build a controlled section with 3 electives + classrooms
d2 = Department.objects.create(name='EE-X')
DepartmentSettings.objects.create(department=d2, lunch_start_slot=5, lunch_end_slot=5, dept_start_slot=1)
c2 = Course.objects.create(department=d2, name='BTECH')
for i in range(4): Room.objects.create(name=f'X{i}', room_id=f'X{i}', room_type='CLASSROOM', capacity=120, department=d2)
s = Section.objects.create(course=c2, year='6', section_name='A', group='G1', class_count=30)
for n in range(3):
    e = Subject.objects.create(name=f'Elective{n}', subject_type='THEORY', duration=50,
                               lectures_per_week=2, section=s, allowed_groups='BOTH', is_elective=True)
    p = Professor.objects.create(name=f'EP{n}', professor_id=f'EP{n}', department=d2, max_workload_hours_per_week=40)
    e.professors.set([p])
a.get('/generate-smart/', follow=True)

el_ts = TimeSlot.objects.filter(section=s, subject__is_elective=True)
ck('all elective sessions scheduled', el_ts.count()==6, f'{el_ts.count()}/6')
# group by (day, slot): each elective period should have the 3 electives together
byslot = defaultdict(set)
for t in el_ts:
    byslot[(t.day, t.slot)].add(t.subject_id)
parallel_periods = [k for k,v in byslot.items() if len(v)==3]
ck('electives run 3-in-parallel in the same slot', len(parallel_periods)>=1,
   f'{[(d,sl,len(v)) for (d,sl),v in byslot.items()]}')
# within a parallel slot, rooms are distinct and profs distinct
ok_rooms=True; ok_prof=True
for (day,slot),subs in byslot.items():
    ts = list(TimeSlot.objects.filter(section=s, day=day, slot=slot, subject__is_elective=True))
    rooms=[t.room_id for t in ts]; profs=[t.professor_id for t in ts]
    if len(rooms)!=len(set(rooms)): ok_rooms=False
    if len(profs)!=len(set(profs)): ok_prof=False
ck('parallel electives use distinct rooms', ok_rooms)
ck('parallel electives use distinct professors', ok_prof)
# section occupies only ONE timetable period per parallel block (slot shared)
ck('section uses one slot per elective period (not 3 separate slots)', len(byslot)<=2,
   f'{len(byslot)} distinct elective slots for 2 periods')

print(f"\nTOTAL: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print('FAILURES:'); [print('  - '+x) for x in FAIL]
teardown_test_environment(); runner.teardown_databases(cfg)
