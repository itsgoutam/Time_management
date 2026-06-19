"""
Role-based session authentication for the timetable app.

Four kinds of identity:
  ADMIN       – StaffAccount(role=ADMIN). Full access to every department.
  DEPT_ADMIN  – StaffAccount(role=DEPT_ADMIN). Strictly one department.
  PROFESSOR   – validated against Professor (name + professor_id). View own timetable.
  STUDENT     – no credentials; picks a section and views it.

Identity lives in request.session, not Django's auth User, because professors and
students are not User rows. See middleware.RoleAccessMiddleware for enforcement.
"""
from functools import wraps
from django.shortcuts import redirect

# ── Roles ───────────────────────────────────────────────────────────────────────
ADMIN = 'ADMIN'
DEPT_ADMIN = 'DEPT_ADMIN'
PROFESSOR = 'PROFESSOR'
STUDENT = 'STUDENT'
STAFF_ROLES = (ADMIN, DEPT_ADMIN)
ALL_ROLES = (ADMIN, DEPT_ADMIN, PROFESSOR, STUDENT)

# Default Administrator seeded on first run. CHANGE THE PASSWORD after first login.
DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_ADMIN_PASSWORD = 'admin123'


# ── Session login / logout ──────────────────────────────────────────────────────
def login_staff(request, account):
    request.session.flush()
    request.session['role'] = account.role
    request.session['account_id'] = account.id
    request.session['display_name'] = account.username
    request.session['department_id'] = account.department_id  # None for full admin


def login_professor(request, professor):
    request.session.flush()
    request.session['role'] = PROFESSOR
    request.session['professor_id'] = professor.id
    request.session['display_name'] = professor.name


def login_student(request, section):
    request.session.flush()
    request.session['role'] = STUDENT
    request.session['section_id'] = section.id
    request.session['display_name'] = f"Student — {section}"


def logout(request):
    request.session.flush()


# ── Session getters ─────────────────────────────────────────────────────────────
def current_role(request):
    return request.session.get('role')


def current_display_name(request):
    return request.session.get('display_name', '')


def current_department_id(request):
    """The department a Dept Admin is scoped to (None for Admin / other roles)."""
    return request.session.get('department_id')


def current_professor_id(request):
    return request.session.get('professor_id')


def current_section_id(request):
    return request.session.get('section_id')


def is_admin(request):
    return current_role(request) == ADMIN


def is_staff(request):
    return current_role(request) in STAFF_ROLES


# ── Seeding ─────────────────────────────────────────────────────────────────────
def seed_default_admin():
    """Create the default Admin account if no Admin exists. Idempotent."""
    from .models import StaffAccount
    if StaffAccount.objects.filter(role=ADMIN).exists():
        return None
    acc = StaffAccount(role=ADMIN, username=DEFAULT_ADMIN_USERNAME, department=None)
    acc.set_password(DEFAULT_ADMIN_PASSWORD)
    acc.save()
    return acc


# ── Department scoping ───────────────────────────────────────────────────────────
def object_department_id(obj):
    """Best-effort: the Department id an object belongs to, or None if global/shared.

    Used to decide whether a Dept Admin may touch a given record.
    """
    from .models import (Department, DepartmentSettings, Course, Room, Section,
                         Subject, Professor, ProfessorOccupiedTime, RoomOccupiedTime)
    if isinstance(obj, Department):
        return obj.id
    if isinstance(obj, DepartmentSettings):
        return obj.department_id
    if isinstance(obj, Course):
        return obj.department_id
    if isinstance(obj, Room):
        return obj.department_id  # may be None (shared room)
    if isinstance(obj, Section):
        return obj.course.department_id
    if isinstance(obj, Subject):
        return obj.section.course.department_id if obj.section_id else None
    from .models import TimeSlot
    if isinstance(obj, TimeSlot):
        return obj.section.course.department_id if obj.section_id else None
    if isinstance(obj, Professor):
        return obj.department_id  # may be None
    if isinstance(obj, ProfessorOccupiedTime):
        return obj.professor.department_id
    if isinstance(obj, RoomOccupiedTime):
        return obj.room.department_id
    return None


def can_access_department(request, dept_id):
    """True if the current user may act on records of department `dept_id`.

    Admin: always. Dept Admin: their own department, plus unassigned records
    (dept_id is None) — e.g. professors/rooms with no department yet — which they
    may claim into their own department by editing them.
    """
    role = current_role(request)
    if role == ADMIN:
        return True
    if role == DEPT_ADMIN:
        return dept_id is None or dept_id == current_department_id(request)
    return False


def can_access_object(request, obj):
    # Shared professors belong to several departments (Professor.departments M2M).
    # A Department Admin may manage a professor mapped to their department, even if
    # the professor's "home" department FK points elsewhere.
    from .models import Professor
    if isinstance(obj, Professor):
        role = current_role(request)
        if role == ADMIN:
            return True
        if role == DEPT_ADMIN:
            did = current_department_id(request)
            if obj.department_id is None or obj.department_id == did:
                return True
            return obj.departments.filter(id=did).exists()
        return False
    return can_access_department(request, object_department_id(obj))


# ── Template context ─────────────────────────────────────────────────────────────
def auth_context(request):
    """Expose the current identity to every template (registered as a context processor)."""
    role = current_role(request)
    dept_name = ''
    dept_id = current_department_id(request)
    if dept_id:
        from .models import Department
        d = Department.objects.filter(id=dept_id).first()
        dept_name = d.name if d else ''
    return {
        'auth_role': role,
        'auth_display_name': current_display_name(request),
        'auth_is_admin': role == ADMIN,
        'auth_is_dept_admin': role == DEPT_ADMIN,
        'auth_is_staff': role in STAFF_ROLES,
        'auth_department_name': dept_name,
    }


# ── View decorators ─────────────────────────────────────────────────────────────
def require_roles(*roles):
    """Decorator: allow only the listed roles; redirect others to login."""
    def deco(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if current_role(request) not in roles:
                return redirect('login')
            return view(request, *args, **kwargs)
        return wrapped
    return deco
