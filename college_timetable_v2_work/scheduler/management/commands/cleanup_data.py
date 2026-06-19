"""
Remove stale / orphaned records that older imports could leave behind.

Safe and idempotent — running it twice changes nothing the second time. It does
NOT touch any record that is still in use (referenced by the timetable, an
assignment, a subject, a department, etc.).

What it cleans:
  • Duplicate professors that share a Teacher_id (collapsed into one - relations
    are moved onto the survivor, the rest deleted).
  • Professors left with NO department by older imports: their department(s) are
    re-derived from the data they are actually used in (the sections of their
    subjects and timetable slots), so they stop floating as "unassigned".
  • Pure-orphan professors: no department (home FK + shared mapping both empty),
    no timetable slots, no teaching assignments, no blocked/fixed times, and not
    referenced by any subject. These are dead leftovers from superseded uploads.

Usage:
    python manage.py cleanup_data            # apply
    python manage.py cleanup_data --dry-run  # report only, change nothing
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db.models import Count

from scheduler.models import Professor, TimeSlot


class Command(BaseCommand):
    help = 'Remove stale/orphaned professor records left by older imports.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Report what would be removed without changing anything.')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        self._unresolved = []
        collapsed = self._collapse_duplicate_ids(dry)
        fixed = self._backfill_departments(dry)
        orphaned = self._remove_orphans(dry)
        verb = 'Would remove' if dry else 'Removed'
        self.stdout.write(self.style.SUCCESS(
            f'{verb}: {collapsed} duplicate professor record(s); '
            f'backfilled department for {fixed} professor(s); '
            f'{orphaned} orphaned professor record(s).'))
        if self._unresolved:
            names = ', '.join(f'{p.name} ({p.professor_id})' for p in self._unresolved)
            self.stdout.write(self.style.WARNING(
                f'NOTE: {len(self._unresolved)} professor(s) still have no department '
                f'because their faculty is not present in the database: {names}. '
                f'Re-import the professors CSV (its Department_name column) to fix them.'))
        if dry:
            self.stdout.write('(dry run - no changes were made)')

    # ── Collapse professors that share a Teacher_id ───────────────────────────
    def _collapse_duplicate_ids(self, dry):
        removed = 0
        dup_ids = (Professor.objects.exclude(professor_id='')
                   .values('professor_id')
                   .annotate(n=Count('id')).filter(n__gt=1)
                   .values_list('professor_id', flat=True))
        for pid in list(dup_ids):
            group = list(Professor.objects.filter(professor_id=pid).order_by('id'))
            keep = max(group, key=self._score)
            for p in group:
                if p.id == keep.id:
                    continue
                self.stdout.write(
                    f'  - duplicate {pid!r}: merging "{p.name}" (id={p.id}) -> '
                    f'"{keep.name}" (id={keep.id})')
                if not dry:
                    TimeSlot.objects.filter(professor=p).update(professor=keep)
                    p.assignments.all().update(professor=keep)
                    p.occupied_times.all().update(professor=keep)
                    p.fixed_slots.all().update(professor=keep)
                    for d in p.departments.all():
                        keep.departments.add(d)
                    for subj in p.subject_set.all():
                        subj.professors.remove(p)
                        subj.professors.add(keep)
                    p.delete()
                removed += 1
        return removed

    # ── Backfill missing departments from real teaching data ─────────────────
    def _backfill_departments(self, dry):
        fixed = 0
        for p in Professor.objects.all():
            if p.department_id or p.departments.exists():
                continue   # already scoped to a department
            # Departments this professor is actually used in: the sections of the
            # subjects they teach, plus the sections of their timetable slots.
            votes = Counter()
            for subj in p.subject_set.select_related('section__course__department'):
                d = getattr(getattr(getattr(subj, 'section', None), 'course', None), 'department', None)
                if d:
                    votes[d.id] += 1
            for ts in TimeSlot.objects.filter(professor=p).select_related('section__course__department'):
                d = getattr(getattr(getattr(ts, 'section', None), 'course', None), 'department', None)
                if d:
                    votes[d.id] += 1
            from scheduler.models import Department
            prefix = p.professor_id.split('-')[0].strip() if p.professor_id else ''
            if not votes and prefix:
                # Fallback 1: SIBLING professors that share this Teacher_id prefix
                # (e.g. other "AS-*" teachers are Applied Science faculty).
                sibs = (Professor.objects
                        .filter(professor_id__istartswith=prefix + '-',
                                department__isnull=False)
                        .exclude(id=p.id))
                votes.update(s.department_id for s in sibs if s.department_id)
            if not votes and prefix:
                # Fallback 2: match the prefix to an existing department's acronym
                # (e.g. "MS" -> "Management Studies", "AS" -> "Applied Science").
                for d in Department.objects.all():
                    acr = ''.join(w[0] for w in d.name.split() if w[:1].isalpha())
                    if acr.upper() == prefix.upper():
                        votes[d.id] += 1
                        break
            if not votes:
                # Could not derive a department (e.g. the professor's faculty no longer
                # exists in the DB). Report it; a professors-CSV re-import will fix it.
                self._unresolved.append(p)
                continue
            dept_ids = list(votes)
            home_id = votes.most_common(1)[0][0]   # most-used department = home
            depts = {d.id: d for d in Department.objects.filter(id__in=dept_ids)}
            home = depts.get(home_id)
            names = ', '.join(sorted(d.name for d in depts.values()))
            self.stdout.write(
                f'  - "{p.name}" (teacher_id={p.professor_id!r}) -> department(s): {names}')
            if not dry:
                p.department = home
                p.save(update_fields=['department'])
                for d in depts.values():
                    p.departments.add(d)
            fixed += 1
        return fixed

    # ── Remove pure-orphan professors ─────────────────────────────────────────
    def _remove_orphans(self, dry):
        removed = 0
        for p in Professor.objects.all():
            if (p.department_id is None
                    and not p.departments.exists()
                    and TimeSlot.objects.filter(professor=p).count() == 0
                    and p.assignments.count() == 0
                    and p.occupied_times.count() == 0
                    and p.fixed_slots.count() == 0
                    and p.subject_set.count() == 0):
                self.stdout.write(
                    f'  - orphan: "{p.name}" (id={p.id}, teacher_id={p.professor_id!r}) - '
                    f'no department, no schedule, no assignments')
                if not dry:
                    p.delete()
                removed += 1
        return removed

    @staticmethod
    def _score(p):
        return (TimeSlot.objects.filter(professor=p).count(),
                p.assignments.count(),
                1 if p.department_id else 0,
                p.id)
