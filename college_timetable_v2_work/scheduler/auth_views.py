"""Login, logout, account management and student routing views."""
import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import IntegrityError

from . import accounts as acc
from .models import StaffAccount, Professor, Department, Course, Section


# ── Login / Logout ───────────────────────────────────────────────────────────────
def _student_section_data():
    """Flat, de-duplicated list of selectable sections for the student picker.

    One entry per (course, semester, effective section name) — groups (G1/G2) are
    merged since students view the combined section timetable. The effective name
    keeps custom sections (I/II/III) distinct.
    """
    seen = set()
    data = []
    sections = (Section.objects
                .select_related('course__department')
                .order_by('course__department__name', 'course__name',
                          'year', 'section_name', 'custom_section_name'))
    for s in sections:
        eff = s.get_effective_section_name()
        key = (s.course_id, s.year, eff)
        if key in seen:
            continue
        seen.add(key)
        data.append({
            'dept_id': s.course.department_id,
            'dept_name': s.course.department.name,
            'course_id': s.course_id,
            'course_name': s.course.get_display_name(),
            'year': s.year,
            'year_label': s.get_year_display_label(),
            'section_name': eff,
            'section_label': eff,
        })
    return data


def login_view(request):
    # Make sure a default Admin exists before anyone tries to log in.
    acc.seed_default_admin()

    # Already logged in → go to the role landing.
    if acc.current_role(request):
        return redirect('dashboard')

    if request.method == 'POST':
        login_type = request.POST.get('login_type', '')

        # ── Admin / Department Admin ──────────────────────────────────────────
        if login_type in ('admin', 'dept_admin'):
            username = (request.POST.get('username') or '').strip()
            password = request.POST.get('password') or ''
            want_role = acc.ADMIN if login_type == 'admin' else acc.DEPT_ADMIN
            account = StaffAccount.objects.filter(username__iexact=username).first()
            if account and account.role == want_role and account.check_password(password):
                acc.login_staff(request, account)
                messages.success(request, f"Welcome, {account.username}.")
                return redirect('dashboard')
            messages.error(request, 'Invalid credentials for that account type.')

        # ── Professor (name + Teacher ID as password) ─────────────────────────
        elif login_type == 'professor':
            name = (request.POST.get('username') or '').strip()
            prof_id = (request.POST.get('password') or '').strip()
            professor = Professor.objects.filter(
                name__iexact=name, professor_id__iexact=prof_id).first()
            if professor and prof_id:
                acc.login_professor(request, professor)
                return redirect('professor_schedule', professor_id=professor.id)
            messages.error(request, 'No professor matches that name and ID.')

        # ── Student (no password — pick course/year/section) ──────────────────
        elif login_type == 'student':
            from django.db.models import Q
            course_id = request.POST.get('course_id')
            year = request.POST.get('year')
            section_name = request.POST.get('section_name')   # effective name (e.g. 'A' or 'I')
            section = (Section.objects
                       .filter(course_id=course_id, year=year)
                       .filter(Q(section_name=section_name)
                               | Q(section_name='CUSTOM', custom_section_name=section_name))
                       .select_related('course').first())
            if section:
                acc.login_student(request, section)
                return redirect('section_combined_timetable',
                                course_id=section.course_id, year=section.year,
                                section_name=section.get_effective_section_name())
            messages.error(request, 'Please choose a valid department, course, semester and section.')

        else:
            messages.error(request, 'Please choose how you want to sign in.')

    return render(request, 'login.html', {
        'student_data_json': json.dumps(_student_section_data()),
    })


def logout_view(request):
    acc.logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('login')


# ── Account management (Admin only) ─────────────────────────────────────────────
def manage_accounts(request):
    accounts = StaffAccount.objects.select_related('department').order_by('role', 'username')
    departments = Department.objects.order_by('name')
    return render(request, 'manage_accounts.html', {
        'accounts': accounts,
        'departments': departments,
    })


def create_account(request):
    if request.method != 'POST':
        return redirect('manage_accounts')
    username = (request.POST.get('username') or '').strip()
    password = request.POST.get('password') or ''
    dept_id = request.POST.get('department')
    if not username or not password or not dept_id:
        messages.error(request, 'Username, password and department are all required.')
        return redirect('manage_accounts')
    department = get_object_or_404(Department, id=dept_id)
    account = StaffAccount(role=acc.DEPT_ADMIN, username=username, department=department)
    account.set_password(password)
    try:
        account.save()
        messages.success(request, f"Department Admin '{username}' created for {department.name}.")
    except IntegrityError:
        messages.error(request, f"A user named '{username}' already exists.")
    return redirect('manage_accounts')


def delete_account(request, account_id):
    account = get_object_or_404(StaffAccount, id=account_id)
    if account.role == acc.ADMIN:
        messages.error(request, 'Admin accounts cannot be deleted here.')
    else:
        name = account.username
        account.delete()
        messages.success(request, f"Removed Department Admin '{name}'.")
    return redirect('manage_accounts')
