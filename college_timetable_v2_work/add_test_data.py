import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'college_timetable.settings')
django.setup()

from scheduler.models import Department, Course, Section, Subject, Professor, Room, TimeSlot

d = Department.objects.create(name="CS")
c = Course.objects.create(department=d, name="BTech")
sec = Section.objects.create(course=c, year="1", section_name="A", group="G1")
prof = Professor.objects.create(name="John Doe", department=d)
room = Room.objects.create(name="101", department=d)
sub = Subject.objects.create(name="Math", subject_type="THEORY", lectures_per_week=3)
sub.professors.add(prof)

ts = TimeSlot.objects.create(day="Monday", slot=1, subject=sub, professor=prof, section=sec, room=room)
print(f"Created TimeSlot ID: {ts.id}")
