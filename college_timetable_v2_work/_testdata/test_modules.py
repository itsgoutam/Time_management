import os, sys, django
sys.path.insert(0, 'D:/college_timetable_v2_work')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'college_timetable.settings')
django.setup()
from django.test.runner import DiscoverRunner
from django.test.utils import setup_test_environment, teardown_test_environment
runner = DiscoverRunner(verbosity=0); cfg = runner.setup_databases(); setup_test_environment()
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from scheduler.models import Department, Course, Section, Professor, Room, Subject, TimeSlot, StaffAccount
from scheduler import accounts as acc

PASS=[]; FAIL=[]
def ck(l, c, extra=''):
    (PASS if c else FAIL).append(l)
    print(('  PASS ' if c else '  FAIL ') + l + (f'  [{extra}]' if extra else ''))
def sec(t): print('\n=== ' + t + ' ===')

base = 'D:/college_timetable_v2_work/_testdata/'
acc.seed_default_admin()
a = Client(); a.post('/login/', {'login_type':'admin','username':'admin','password':'admin123'})
files = {f'{k}_csv': SimpleUploadedFile(f'{k}.csv', open(base+f'{k}.csv','rb').read(), content_type='text/csv')
         for k in ['dept_settings','rooms','professors','sections','subjects']}
a.post('/csv-upload/', dict(files, auto_generate='on'), follow=True)

cse = Department.objects.get(name__startswith='Computer')
course = Course.objects.filter(department=cse).first()
sect = Section.objects.filter(course__department=cse, group='G1').first()
prof = Professor.objects.get(professor_id='CS001')
room = Room.objects.filter(department=cse, room_type='CLASSROOM').first()
yr = sect.year                              # semester value, e.g. '3'
sn = sect.get_effective_section_name()      # effective section name, e.g. 'I'

def g(url, ctype=None):
    try:
        r = a.get(url)
    except Exception as e:
        print(f'    EXCEPTION on {url}: {type(e).__name__}: {e}')
        class _R: status_code=500
        return False, _R()
    ok = r.status_code == 200
    if ctype:
        ok = ok and ctype in r.get('Content-Type','')
    return ok, r

sec('5. VIEW MODULES (admin)')
ck('dashboard /', g('/')[0])
ck('csv upload page', g('/csv-upload/')[0])
ck('workload report', g('/workload-report/')[0])
ck('workload report CSV', g('/workload-report/csv/', 'csv')[0])
ck('free rooms', g('/free-rooms/')[0])
ck('free students (dean view)', g('/free-students/')[0])
ck('combine edit', g('/combine-edit/')[0])
ck('manage accounts', g('/accounts/')[0])
ck('dept settings page', g(f'/department/{cse.id}/settings/')[0])
ck('section timetable', g(f'/timetable/{sect.id}/')[0])
ck('professor schedule', g(f'/professor/{prof.id}/')[0])
ck('professor schedule has timeslots', TimeSlot.objects.filter(professor=prof).exists())
ck('room schedule', g(f'/room/{room.id}/')[0])
ck('year timetable', g(f'/year-timetable/{course.id}/{yr}/')[0])
ck('combined section timetable', g(f'/section-timetable/{course.id}/{yr}/{sn}/')[0])
ck('api professor blocks (json)', g(f'/api/professor/{prof.id}/blocks/', 'json')[0])

sec('6. DOWNLOAD TEMPLATES')
for t in ['subjects','professors','rooms','sections','dept_settings']:
    ck(f'template {t}', g(f'/csv-template/{t}/', 'csv')[0])

sec('7. EXPORTS (PDF / CSV / QR)')
ck('section PDF', g(f'/timetable/{sect.id}/pdf/', 'pdf')[0])
ck('section CSV', g(f'/timetable/{sect.id}/csv/', 'csv')[0])
ck('section QR (png)', g(f'/timetable/{sect.id}/qr/', 'png')[0])
ck('professor PDF', g(f'/professor/{prof.id}/pdf/', 'pdf')[0])
ck('professor CSV', g(f'/professor/{prof.id}/csv/', 'csv')[0])
ck('professor QR (png)', g(f'/professor/{prof.id}/qr/', 'png')[0])
ck('room PDF', g(f'/room/{room.id}/pdf/', 'pdf')[0])
ck('room CSV', g(f'/room/{room.id}/csv/', 'csv')[0])
ck('year PDF', g(f'/year-timetable/{course.id}/{yr}/pdf/', 'pdf')[0])
ck('combined section PDF', g(f'/section-timetable/{course.id}/{yr}/{sn}/pdf/', 'pdf')[0])
ck('department PDF', g(f'/department/{cse.id}/pdf/', 'pdf')[0])
ck('free rooms PDF', g('/free-rooms/pdf/', 'pdf')[0])

sec('8. EDIT/ADD FORMS RENDER')
ck('add professor form', g('/add-professor/')[0])
ck('add section form', g('/add-section/')[0])
ck('add subject form', g('/add-subject/')[0])
ck('add room form', g('/add-room/')[0])
ck('add course form', g('/add-course/')[0])
ck('add department form', g('/add-department/')[0])
ck('edit professor form', g(f'/edit-professor/{prof.id}/')[0])
ck('edit section form', g(f'/edit-section/{sect.id}/')[0])
ck('edit room form', g(f'/edit-room/{room.id}/')[0])

sec('9. ROLE LOGINS & ACCESS CONTROL')
a.post('/accounts/create/', {'username':'cse_admin','password':'pw123','department':cse.id})
ck('admin created dept admin', StaffAccount.objects.filter(username='cse_admin').exists())
d = Client(); d.post('/login/', {'login_type':'dept_admin','username':'cse_admin','password':'pw123'})
ck('dept admin login', d.session.get('role')=='DEPT_ADMIN')
dash = d.get('/').content.decode()
ck('dept admin dashboard shows own dept (CSE)', 'Computer Science' in dash)
ck('dept admin dashboard hides Mechanical', 'Mechanical' not in dash)
ece = Department.objects.get(name__startswith='Electronics')
ece_sec = Section.objects.filter(course__department=ece).first()
ck('dept admin blocked from other dept section (403)', d.get(f'/edit-section/{ece_sec.id}/').status_code==403)
ck('dept admin blocked from manage accounts (403)', d.get('/accounts/').status_code==403)
p = Client(); p.post('/login/', {'login_type':'professor','username':'Dr. Sandeep Kad','password':'CS001'})
ck('professor login (name+id from CSV)', p.session.get('role')=='PROFESSOR')
ck('professor sees own schedule', p.get(f'/professor/{prof.id}/').status_code==200)
other = Professor.objects.exclude(id=prof.id).first()
ck('professor blocked from other prof schedule (403)', p.get(f'/professor/{other.id}/').status_code==403)
ck('professor blocked from csv upload (403)', p.get('/csv-upload/').status_code==403)
s = Client(); rs = s.post('/login/', {'login_type':'student','course_id':course.id,'year':yr,'section_name':sn}, follow=True)
ck('student login -> timetable', rs.status_code==200 and s.session.get('role')=='STUDENT')
ck('student blocked from add-section (403)', s.get('/add-section/').status_code==403)
ck('unauthenticated -> redirect to login', Client().get('/', follow=False).status_code==302)

print(f"\nMODULE TOTAL: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print('FAILURES:')
    for x in FAIL: print('  - ' + x)
teardown_test_environment(); runner.teardown_databases(cfg)
