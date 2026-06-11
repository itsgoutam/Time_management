import os, sys, django, io
sys.path.insert(0, 'D:/college_timetable_v2_work')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'college_timetable.settings')
django.setup()
from django.test.runner import DiscoverRunner
from django.test.utils import setup_test_environment, teardown_test_environment
runner = DiscoverRunner(verbosity=0); cfg = runner.setup_databases(); setup_test_environment()
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from scheduler.models import (Department, DepartmentSettings, Course, Section, Professor,
                              Room, Subject, TimeSlot, ProfessorOccupiedTime, ProfessorFixedSlot)
from scheduler.csv_import import import_professors, run_full_import
from scheduler import accounts as acc

PASS=[]; FAIL=[]
def ck(l,c,extra=''):
    (PASS if c else FAIL).append(l); print(('  PASS ' if c else '  FAIL ')+l+(f'  [{extra}]' if extra else ''))
def sec(t): print('\n=== '+t+' ===')

acc.seed_default_admin()
admin = Client(); admin.post('/login/', {'login_type':'admin','username':'admin','password':'admin123'})

def reset():
    for M in (TimeSlot, Subject, ProfessorFixedSlot, ProfessorOccupiedTime, Section,
              Course, Professor, Room, DepartmentSettings, Department):
        M.objects.all().delete()

# ════════════════════════════════════════════════════════════════════════════
sec('1. NO FIXED ROOM -> room auto-picked from the SAME department')
reset()
cse = Department.objects.create(name='CSE'); ece = Department.objects.create(name='ECE')
for d in (cse, ece): DepartmentSettings.objects.create(department=d, lunch_start_slot=5, lunch_end_slot=5, dept_start_slot=1)
ccse = Course.objects.create(department=cse, name='BTECH')
# CSE rooms (no fixed room on the section) + an ECE room that should NOT be used
Room.objects.create(name='CSE-A', room_id='CR1', room_type='CLASSROOM', capacity=120, department=cse)
Room.objects.create(name='CSE-B', room_id='CR2', room_type='CLASSROOM', capacity=120, department=cse)
Room.objects.create(name='ECE-A', room_id='ER1', room_type='CLASSROOM', capacity=120, department=ece)
s = Section.objects.create(course=ccse, year='3RD', section_name='A', group='G1', class_count=30, fixed_room=None)
sub = Subject.objects.create(name='DBMS', subject_type='THEORY', duration=50, lectures_per_week=3, section=s, allowed_groups='BOTH')
prof = Professor.objects.create(name='P', professor_id='P1', department=cse, max_workload_hours_per_week=40); sub.professors.set([prof])
admin.get('/generate-smart/', follow=True)
rooms_used = set(TimeSlot.objects.filter(section=s).values_list('room__department__name', flat=True))
ck('section with no fixed room got a room', TimeSlot.objects.filter(section=s, room__isnull=False).exists())
ck('auto-assigned room is from the SAME department (CSE), not ECE', rooms_used=={'CSE'}, f'{rooms_used}')

# ════════════════════════════════════════════════════════════════════════════
sec('2. SECTION day & start-time EMPTY -> fall back to department settings')
reset()
# dept starts at slot 3 (10:40) and lunch at slot 6
dep = Department.objects.create(name='CSE')
DepartmentSettings.objects.create(department=dep, lunch_start_slot=6, lunch_end_slot=6, dept_start_slot=3)
c = Course.objects.create(department=dep, name='BTECH')
Room.objects.create(name='R', room_id='R1', room_type='CLASSROOM', capacity=120, department=dep)
# Import a section with EMPTY Day and EMPTY Section_Start_time
SECCSV = ('Department,Semester,section,group,Fixed_room,Course,Program Name,Free_day,Class_Count,Day,Section_Start_time\n'
          'CSE,3rd,A,G1,,B.TECH,CSE,,30,,\n')
errs=[]; warns=[]
from scheduler.csv_import import import_sections
import_sections(io.BytesIO(SECCSV.encode()), errs, warns)
s = Section.objects.get(course__department=dep)
ck('empty Section_Start_time -> section.section_start_slot is None (uses dept default)', s.section_start_slot is None)
sub = Subject.objects.create(name='OS', subject_type='THEORY', duration=50, lectures_per_week=4, section=s, allowed_groups='BOTH')
prof = Professor.objects.create(name='Q', professor_id='Q1', department=dep, max_workload_hours_per_week=40); sub.professors.set([prof])
admin.get('/generate-smart/', follow=True)
slots_used = sorted(set(TimeSlot.objects.filter(section=s).values_list('slot', flat=True)))
ck('no class before department start slot (3 / 10:40)', all(sl >= 3 for sl in slots_used), f'slots={slots_used}')
ck('no class during department lunch slot (6)', 6 not in slots_used, f'slots={slots_used}')

# ════════════════════════════════════════════════════════════════════════════
sec('3. BLOCKED time (unavailable) and FIXED time (reserved)')
reset()
base='D:/college_timetable_v2_work/_testdata/'
files={k:open(base+f'{k}.csv','rb') for k in ['dept_settings','rooms','professors','sections','subjects']}
run_full_import(files)
for f in files.values(): f.close()
admin.get('/generate-smart/', follow=True)
# Block: Ajay (CS002) blocked Monday 9:00-9:50 (slot 1) and Friday 2:00-2:50 (slot 7)
ajay = Professor.objects.get(professor_id='CS002')
blk_viol = 0
for occ in ProfessorOccupiedTime.objects.filter(professor=ajay):
    for sl in occ.blocked_slots():
        if TimeSlot.objects.filter(professor=ajay, day=occ.day, slot=sl).exists(): blk_viol += 1
ck('professor has NO class during a blocked time', blk_viol==0, f'{ProfessorOccupiedTime.objects.filter(professor=ajay).count()} blocks checked')
# Fixed: every professor reserved at their fixed slot (no class there)
fx_viol = 0
for fx in ProfessorFixedSlot.objects.all():
    for sl in fx.blocked_slots():
        if TimeSlot.objects.filter(professor=fx.professor, day=fx.day, slot=sl).exists(): fx_viol += 1
ck('professor reserved (no other class) at every fixed slot', fx_viol==0, f'{ProfessorFixedSlot.objects.count()} fixed slots checked')
# Fixed slot shows on the professor grid
sandeep = Professor.objects.get(professor_id='CS001')
ck('fixed slot visible on professor timetable grid', b'cell-fixed' in admin.get(f'/professor/{sandeep.id}/').content)

# ════════════════════════════════════════════════════════════════════════════
sec('4. MAX WORKLOAD persistence / keep-the-max')
reset()
Department.objects.create(name='CSE')
# (a) stated ONCE (13) then blank on later rows -> stays 13
CSV_A = ('Department Name,Teacher_id,Teacher_name,Max_Workload_Hours_per_week,Subject Name,"Dept Name,Prog Name,Sem,Sec",Block_time_slot(day/time)\n'
         'CSE,X1,Dr One,13,DBMS,,\n'
         'CSE,X1,Dr One,,OS,,\n'
         'CSE,X1,Dr One,,AI,,\n')
import_professors(io.BytesIO(CSV_A.encode()), [], [])
p1 = Professor.objects.get(professor_id='X1')
ck('workload stated once (13) persists across blank rows', p1.max_workload_hours_per_week==13, f'{p1.max_workload_hours_per_week}')
# (b) stated multiple times (20 then 10) -> keep the MAX (20), not the last
CSV_B = ('Department Name,Teacher_id,Teacher_name,Max_Workload_Hours_per_week,Subject Name,"Dept Name,Prog Name,Sem,Sec",Block_time_slot(day/time)\n'
         'CSE,X2,Dr Two,20,DBMS,,\n'
         'CSE,X2,Dr Two,10,OS,,\n')
import_professors(io.BytesIO(CSV_B.encode()), [], [])
p2 = Professor.objects.get(professor_id='X2')
ck('workload stated 20 then 10 -> keeps MAX (20)', p2.max_workload_hours_per_week==20, f'{p2.max_workload_hours_per_week}')
# (c) blank first, explicit later (15) -> takes the explicit value over default 20
CSV_C = ('Department Name,Teacher_id,Teacher_name,Max_Workload_Hours_per_week,Subject Name,"Dept Name,Prog Name,Sem,Sec",Block_time_slot(day/time)\n'
         'CSE,X3,Dr Three,,DBMS,,\n'
         'CSE,X3,Dr Three,15,OS,,\n')
import_professors(io.BytesIO(CSV_C.encode()), [], [])
p3 = Professor.objects.get(professor_id='X3')
ck('blank-first then 15 -> uses explicit 15 (not default 20)', p3.max_workload_hours_per_week==15, f'{p3.max_workload_hours_per_week}')

print(f"\nTOTAL: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print('FAILURES:'); [print('  - '+x) for x in FAIL]
teardown_test_environment(); runner.teardown_databases(cfg)
