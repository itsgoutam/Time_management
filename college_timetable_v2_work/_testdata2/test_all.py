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
from scheduler.models import (Department, Professor, Room, Subject, Section, TimeSlot,
                              TeachingAssignment, StaffAccount)
from scheduler import accounts as acc

P=[]; F=[]
def ck(l,c,extra=''):
    (P if c else F).append(l); print(('  PASS ' if c else '  FAIL ')+l+(f'  [{extra}]' if extra else ''))
def sec(t): print('\n=== '+t+' ===')

base='D:/college_timetable_v2_work/_testdata2/'
acc.seed_default_admin()
a=Client(); a.post('/login/', {'login_type':'admin','username':'admin','password':'admin123'})

sec('1. IMPORT + GENERATE the dataset')
files={f'{k}_csv':SimpleUploadedFile(f'{k}.csv',open(base+f'{k}.csv','rb').read(),content_type='text/csv') for k in ['dept_settings','rooms','professors','sections','subjects']}
r=a.post('/csv-upload/', dict(files, auto_generate='on'), follow=True)
ck('upload+generate ok', r.status_code==200)
ck('professors imported', Professor.objects.count()>=25, str(Professor.objects.count()))
ck('explicit teaching assignments recorded', TeachingAssignment.objects.count()>0, str(TeachingAssignment.objects.count()))
ck('timeslots generated', TimeSlot.objects.count()>0, str(TimeSlot.objects.count()))

sec('2. WORKLOAD within limit (true contact hours = distinct day/slot taught)')
def prof_minutes(pid):
    # A professor's real workload = the distinct (day, slot) cells they teach.
    # Shared lectures (theory G1+G2, course-wide electives) occupy one cell = one
    # hour; a lab's two slots are two cells = two hours.
    slots = set(TimeSlot.objects.filter(professor_id=pid).values_list('day', 'slot'))
    return len(slots) * 50
over=[]
for p in Professor.objects.all():
    used_h = prof_minutes(p.id)/60.0
    lim = p.max_workload_hours_per_week
    if used_h > lim + 0.01:
        over.append((p.name, round(used_h,1), lim))
ck('no professor exceeds their workload limit', not over, str(over[:5]))

sec('3. WORKLOAD only from ASSIGNED subjects (explicit honoured)')
# A "hard" mismatch = a professor who HAS explicit assignments teaching a REGULAR
# (non-elective) subject that is NOT one of theirs. Orphan electives (no teacher
# named anywhere in the CSV) assigned to spare-capacity profs are acceptable.
orphan_subject_names = set()
for s in Subject.objects.filter(is_elective=True):
    if not TeachingAssignment.objects.filter(subject_name__iexact=s.name).exists():
        orphan_subject_names.add(s.name.strip().lower())
hard=[]; orphan_assigns=0
for p in Professor.objects.filter(assignments__isnull=False).distinct():
    assigned_names={ta.subject_name.strip().lower() for ta in p.assignments.all()}
    for t in TimeSlot.objects.filter(professor=p).select_related('subject'):
        nm=t.subject.name.strip().lower()
        base_nm = nm[:-len(' tutorial')] if nm.endswith(' tutorial') else nm
        if base_nm in assigned_names or nm in assigned_names:
            continue
        if t.subject.is_elective:
            orphan_assigns+=1   # acceptable: elective with no named teacher
        else:
            hard.append((p.name, t.subject.name))
ck('no professor teaches a REGULAR subject that is not theirs', len(hard)==0,
   f'{len(hard)} hard mismatches; {orphan_assigns} orphan-elective assigns (data gap)')

sec('4. Specific explicit assignment honoured (spot checks)')
def teaches(prof_name, subj_substr, sem, secname):
    p=Professor.objects.filter(name=prof_name).first()
    if not p: return False
    return TimeSlot.objects.filter(professor=p, subject__name__icontains=subj_substr,
                                   section__year=sem, section__custom_section_name=secname).exists()
ck('Dr. Sandeep Kad teaches Operating Systems for 4th COE',
   teaches('Dr. Sandeep Kad','Operating Systems','4','COE'))
ck('Ms. Shagun Arora teaches Operating Systems for 4th CS-1',
   teaches('Ms. Shagun Arora','Operating Systems','4','CS-1'))

sec('5. ELECTIVES parallel + multi-display')
# find a section/day/slot with >1 elective
byslot=defaultdict(list)
for t in TimeSlot.objects.filter(subject__is_elective=True).select_related('section'):
    byslot[(t.section_id,t.day,t.slot)].append(t)
parallel=[k for k,v in byslot.items() if len(v)>1]
print('   elective parallel blocks:', len(parallel), '| total elective slots:', TimeSlot.objects.filter(subject__is_elective=True).count())
ck('elective subjects exist & scheduled', TimeSlot.objects.filter(subject__is_elective=True).exists())

sec('6. ACCOUNTS persist + dept dropdown from dept_settings')
a.post('/accounts/create/', {'username':'cse_admin','password':'pw','department':Department.objects.first().id})
ck('dept admin created', StaffAccount.objects.filter(username='cse_admin').exists())
# regenerate + re-upload should NOT remove the account
a.get('/generate-smart/', follow=True)
a.post('/csv-upload/', {f'{k}_csv':SimpleUploadedFile(f'{k}.csv',open(base+f'{k}.csv','rb').read()) for k in ['professors']}, follow=True)
ck('account persists after generate + re-upload', StaffAccount.objects.filter(username='cse_admin').exists())
# manage accounts page lists departments (from dept_settings)
mhtml=a.get('/accounts/').content.decode()
ck('dept dropdown lists the dept_settings department', 'Computer Science' in mhtml)

sec('7. DELETE ALL button')
before=(Professor.objects.count(), Room.objects.count(), TimeSlot.objects.count())
a.post('/delete-all/', follow=True)
ck('all professors deleted', Professor.objects.count()==0)
ck('all rooms deleted', Room.objects.count()==0)
ck('timetable cleared', TimeSlot.objects.count()==0)
ck('sections kept', Section.objects.count()>0)
ck('subjects kept', Subject.objects.count()>0)
ck('accounts kept after delete-all', StaffAccount.objects.filter(username='cse_admin').exists())
# dept admin cannot delete-all
d=Client(); d.post('/login/', {'login_type':'dept_admin','username':'cse_admin','password':'pw'})
ck('dept admin blocked from delete-all (403)', d.post('/delete-all/').status_code==403)

print(f"\nTOTAL: {len(P)} passed, {len(F)} failed")
for x in F: print('  FAIL:', x)
teardown_test_environment(); runner.teardown_databases(cfg)
