"""Load the test data into the REAL database and generate the timetable,
so it can be viewed in the running app. Keeps StaffAccount (logins)."""
import os, sys, django
sys.path.insert(0, 'D:/college_timetable_v2_work')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'college_timetable.settings')
django.setup()
from django.test import Client
from scheduler.models import (Department, Course, Section, Professor, Room, Subject,
                              TimeSlot, ProfessorFixedSlot, ProfessorOccupiedTime,
                              RoomOccupiedTime, DepartmentSettings, CSVImportLog)
from scheduler.csv_import import run_full_import
from scheduler import accounts as acc

base = 'D:/college_timetable_v2_work/_testdata/'

# 1. Clean slate (keep StaffAccount logins).
for M in (TimeSlot, Subject, ProfessorFixedSlot, ProfessorOccupiedTime, RoomOccupiedTime,
          Section, Course, Professor, Room, DepartmentSettings, Department, CSVImportLog):
    M.objects.all().delete()
acc.seed_default_admin()

# 2. Import the 5 CSVs.
files = {k: open(base + f'{k}.csv', 'rb') for k in
         ['dept_settings', 'rooms', 'professors', 'sections', 'subjects']}
counts, errors, warnings = run_full_import(files)
for f in files.values():
    f.close()
print('Imported:', counts)
if errors:
    print('Errors:', errors)
print(f'Warnings: {len(warnings)} (data quirks, non-fatal)')

# 3. Generate the timetable through the real view.
c = Client()
c.post('/login/', {'login_type': 'admin', 'username': 'admin', 'password': 'admin123'})
c.get('/generate-smart/', follow=True)
print('\nTimeslots generated:', TimeSlot.objects.count())

# 4. Report professor timetables.
print('\nProfessor timetables:')
for p in Professor.objects.order_by('name'):
    n = TimeSlot.objects.filter(professor=p).count()
    print(f'  {p.name:24} login: {p.name} / {p.professor_id:6}  classes={n}')
print('\nLog in at /login/ as admin/admin123, or as any professor above (name + ID).')
