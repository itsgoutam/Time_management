import os, sys, django
sys.path.insert(0, 'D:/college_timetable_v2_work')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'college_timetable.settings')
django.setup()
from django.test.runner import DiscoverRunner
from django.test.utils import setup_test_environment, teardown_test_environment
runner = DiscoverRunner(verbosity=0); cfg = runner.setup_databases(); setup_test_environment()
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from scheduler.models import Department, Course, Section, Subject
from scheduler import accounts as acc

PASS=[]; FAIL=[]
def ck(l,c,extra=''):
    (PASS if c else FAIL).append(l); print(('  PASS ' if c else '  FAIL ')+l+(f'  [{extra}]' if extra else ''))
def sec(t): print('\n=== '+t+' ===')

base='D:/college_timetable_v2_work/_testdata/'
acc.seed_default_admin()
a=Client(); a.post('/login/', {'login_type':'admin','username':'admin','password':'admin123'})
files={f'{k}_csv':SimpleUploadedFile(f'{k}.csv',open(base+f'{k}.csv','rb').read(),content_type='text/csv') for k in ['dept_settings','rooms','professors','sections','subjects']}
a.post('/csv-upload/', dict(files, auto_generate='on'), follow=True)

cse = Department.objects.get(name__startswith='Computer')
course = Course.objects.filter(department=cse).first()

sec('1. SEMESTER mapping (CSV 3rd->3, 5th->5)')
sems = sorted(set(Section.objects.values_list('year', flat=True)))
ck('section semesters stored as digits (3, 5 ...)', all(v.isdigit() for v in sems), f'{sems}')
s3 = Section.objects.filter(year='3').first()
ck('CSV "3rd" -> semester 3', s3 is not None)
ck('semester display label is "Semester 3"', s3.get_year_display_label()=='Semester 3', s3.get_year_display_label())
s5 = Section.objects.filter(year='5').first()
ck('CSV "5th" -> semester 5 (no longer CUSTOM)', s5 is not None and s5.get_year_display_label()=='Semester 5')
# subject semester filter matched correctly
ck('subjects linked to sem-3 sections exist', Subject.objects.filter(section__year='3').exists())
ck('subjects linked to sem-5 sections exist', Subject.objects.filter(section__year='5').exists())

sec('2. UI shows "Semester" not "Year"')
dash = a.get('/').content.decode()
ck('dashboard tree shows "Semester 3"', 'Semester 3' in dash)
ck('dashboard no longer shows "3rd Year"', '3rd Year' not in dash and '3RD' not in dash)
yt = a.get(f'/year-timetable/{course.id}/3/').content.decode()
ck('semester timetable page shows "Semester 3"', 'Semester 3' in yt)

sec('3. GROUPS TAB — custom sections I/II/III stay distinct')
# CSE sem-3 has sections I(G1), II(G2), III(G3) — all custom names
sem3 = Section.objects.filter(course=course, year='3')
effnames = sorted(set(x.get_effective_section_name() for x in sem3))
print('   sem-3 effective section names:', effnames)
ck('three distinct custom sections (I, II, III) exist', set(effnames) >= {'I','II','III'})
# dashboard tree must list each as its own node (regroup by effective name)
ck('tree shows Section I, II and III separately',
   all(f'Section {n}' in dash for n in ('I','II','III')))
# combined-timetable view addresses each distinct section by effective name
for n in ('I','II','III'):
    r = a.get(f'/section-timetable/{course.id}/3/{n}/')
    grp = r.content.decode()
    ck(f'combined view for Section {n} loads its own group only',
       r.status_code==200 and f'Section {n}' in grp)
# Section I should show ONLY G1 (not G2/G3 merged in)
secI_groups = sorted(Section.objects.filter(course=course, year='3', section_name='CUSTOM', custom_section_name='I').values_list('group', flat=True))
ck('Section I has exactly its own group(s), not merged', secI_groups==['G1'], f'{secI_groups}')

sec('4. STUDENT picker keeps custom sections distinct')
from scheduler.auth_views import _student_section_data
data = _student_section_data()
cse_sem3 = sorted({d['section_name'] for d in data if d['dept_name'].startswith('Computer') and d['year']=='3'})
ck('student picker lists I, II, III separately (not one "CUSTOM")', set(cse_sem3) >= {'I','II','III'}, f'{cse_sem3}')
# student can log in to a specific custom section
sc = Client()
rs = sc.post('/login/', {'login_type':'student','course_id':course.id,'year':'3','section_name':'II'}, follow=True)
ck('student login to Section II works', rs.status_code==200 and sc.session.get('role')=='STUDENT')

print(f"\nTOTAL: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print('FAILURES:'); [print('  - '+x) for x in FAIL]
teardown_test_environment(); runner.teardown_databases(cfg)
