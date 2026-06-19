# GTM SmartSchedule

GTM SmartSchedule is a comprehensive and intelligent timetable scheduler application built with Django. It provides a robust set of features to handle college scheduling, including conflict management, resource allocation, and reporting.

![AGC Logo](agclogo.jpg)

## Features

### 1. Smart Conflict Handling
All scheduling conflicts are enforced strictly within the generator:
- Prevent overlaps between Professor occupied times and room occupied times.
- Both professor and room busyness are evaluated before scheduling.
- Guarantees no classes are placed in blocked professor or room slots.

### 2. Quick Professor Block
Provides a streamlined "Quick Professor Block" panel during subject assignment.
- Select professor, day, start slot, end slot, and activity type.
- Blocks are saved instantly without reloading the page.
- Blocked slots are permanently respected by the timetable generator.
- Easy to manage and delete quick blocks directly from the panel.

### 3. Lab / Room Occupancy Management
Effectively manage room and lab usage.
- Block specific time slots for Workshops, Seminars, Maintenance, Examinations, or College Events.
- Blocked slots are clearly visually represented as "🚧" cells in the room timetable grid.
- Allows editing and deleting of individual room blocks.

### 4. Optimization Reporting
In-depth reporting after timetable generation.
- **Workload Balance**: Calculates average hours per week, flagging professors who are overloaded (>140%) or underutilised (<60%).
- **Lab Utilisation**: Identifies labs with low usage (≤2 slots used per week).
- Provides actionable insight banners after generation.

## Setup & Run Instructions

### Requirements
You will need Python installed. Install the following required packages using `pip`:

```bash
pip install django qrcode pillow reportlab
```

### First-Time Setup
Navigate into the project directory and run migrations to set up the database.

```bash
cd college_timetable_v2_work
python manage.py migrate
```

Start the local server:
```bash
python manage.py runserver
```

### Re-Run
If the database has already been migrated, you can simply start the server:

```bash
cd college_timetable_v2_work
python manage.py runserver
```

Then, open your web browser and navigate to: http://127.0.0.1:8000/

## Screenshots
*(Add more screenshots here demonstrating the Quick Professor Block, Room Occupancy Grid, and Optimization Reports.)*
