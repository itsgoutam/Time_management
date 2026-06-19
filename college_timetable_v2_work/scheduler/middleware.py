"""
RoleAccessMiddleware — enforces the login-required lockdown and coarse role
authorization for every request.

Fine-grained department scoping (a Dept Admin may only touch their own
department's records) is enforced inside the individual views via
accounts.can_access_object, because it needs the fetched object.
"""
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from . import accounts as acc

# Views reachable without being logged in.
PUBLIC_NAMES = {'login', 'logout'}

# Department Admins are blocked from these (Admin-only).
# NOTE: 'delete_all' is intentionally NOT here — a Department Admin may delete
# their OWN department's data. The delete_all view enforces the per-department
# scope on the backend (see views.delete_all).
ADMIN_ONLY_NAMES = {
    'manage_accounts', 'create_account', 'delete_account',
    'add_department', 'edit_department', 'delete_department',
}

# A Professor may only reach their own timetable + exports.
# 'dashboard' is allowed but the view itself redirects them to their schedule.
PROFESSOR_NAMES = {
    'dashboard', 'professor_schedule', 'export_professor_pdf', 'qr_professor',
    'export_professor_csv_view', 'api_professor_blocks', 'logout',
}

# A Student may only reach timetable view/export pages + the selector.
# 'dashboard' is allowed but the view redirects them to their section timetable.
STUDENT_NAMES = {
    'dashboard', 'section_combined_timetable', 'export_section_combined_pdf',
    'section_timetable', 'export_pdf', 'qr_timetable', 'export_section_csv',
    'year_timetable', 'export_year_pdf', 'logout',
}

_FORBIDDEN = HttpResponseForbidden(
    '<h1>403 — Access denied</h1>'
    '<p>Your account does not have permission to view this page.</p>'
    '<p><a href="/logout/">Log out</a></p>')


class RoleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Let Django's own admin site manage its own auth.
        if request.path.startswith('/admin/'):
            return None

        match = request.resolver_match
        url_name = match.url_name if match else None
        if url_name in PUBLIC_NAMES:
            return None

        role = acc.current_role(request)
        if role is None:
            return redirect('login')

        if role == acc.ADMIN:
            return None

        if role == acc.DEPT_ADMIN:
            if url_name in ADMIN_ONLY_NAMES:
                return _FORBIDDEN
            return None  # per-object dept scoping happens in the views

        if role == acc.PROFESSOR:
            if url_name not in PROFESSOR_NAMES:
                return _FORBIDDEN
            pid = view_kwargs.get('professor_id')
            if pid is not None and str(pid) != str(acc.current_professor_id(request)):
                return _FORBIDDEN
            return None

        if role == acc.STUDENT:
            if url_name not in STUDENT_NAMES:
                return _FORBIDDEN
            return None

        return redirect('login')
