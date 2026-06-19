from django.urls import path
from . import views
from . import auth_views

urlpatterns = [
    # Authentication & accounts
    path('login/', auth_views.login_view, name='login'),
    path('logout/', auth_views.logout_view, name='logout'),
    path('accounts/', auth_views.manage_accounts, name='manage_accounts'),
    path('accounts/create/', auth_views.create_account, name='create_account'),
    path('accounts/<int:account_id>/delete/', auth_views.delete_account, name='delete_account'),

    path('', views.dashboard, name='dashboard'),
    path('delete-all/', views.delete_all, name='delete_all'),

    # Department
    path('add-department/', views.add_department, name='add_department'),
    path('edit-department/<int:dept_id>/', views.edit_department, name='edit_department'),
    path('delete-department/<int:dept_id>/', views.delete_department, name='delete_department'),
    path('department/<int:dept_id>/pdf/', views.export_department_pdf, name='export_department_pdf'),
    path('department/<int:dept_id>/settings/', views.dept_settings, name='dept_settings'),

    # Course
    path('add-course/', views.add_course, name='add_course'),
    path('edit-course/<int:course_id>/', views.edit_course, name='edit_course'),
    path('delete-course/<int:course_id>/', views.delete_course, name='delete_course'),

    # Room
    path('add-room/', views.add_room, name='add_room'),
    path('edit-room/<int:room_id>/', views.edit_room, name='edit_room'),
    path('delete-room/<int:room_id>/', views.delete_room, name='delete_room'),
    path('room/<int:room_id>/', views.room_schedule, name='room_schedule'),
    path('room/<int:room_id>/pdf/', views.export_room_pdf, name='export_room_pdf'),
    path('room/<int:room_id>/csv/', views.export_room_csv, name='export_room_csv'),

    # Room Occupied Time
    path('room/<int:room_id>/add-occupied/', views.add_room_occupied, name='add_room_occupied'),
    path('room-occupied/<int:occupied_id>/edit/', views.edit_room_occupied, name='edit_room_occupied'),
    path('room-occupied/<int:occupied_id>/delete/', views.delete_room_occupied, name='delete_room_occupied'),

    # Section
    path('add-section/', views.add_section, name='add_section'),
    path('edit-section/<int:section_id>/', views.edit_section, name='edit_section'),
    path('delete-section/<int:section_id>/', views.delete_section, name='delete_section'),

    # Subject
    path('add-subject/', views.add_subject, name='add_subject'),
    path('edit-subject/<int:subject_id>/', views.edit_subject, name='edit_subject'),
    path('delete-subject/<int:subject_id>/', views.delete_subject, name='delete_subject'),

    # Professor
    path('add-professor/', views.add_professor, name='add_professor'),
    path('edit-professor/<int:professor_id>/', views.edit_professor, name='edit_professor'),
    path('delete-professor/<int:professor_id>/', views.delete_professor, name='delete_professor'),
    path('professor/<int:professor_id>/', views.professor_schedule, name='professor_schedule'),
    path('professor/<int:professor_id>/pdf/', views.export_professor_pdf, name='export_professor_pdf'),
    path('professor/<int:professor_id>/qr/', views.qr_professor, name='qr_professor'),
    path('professor/<int:professor_id>/csv/', views.export_professor_csv, name='export_professor_csv_view'),

    # Professor Occupied Time
    path('professor/<int:professor_id>/add-occupied-time/', views.add_occupied_time, name='add_occupied_time'),
    path('occupied-time/<int:occupied_id>/edit/', views.edit_occupied_time, name='edit_occupied_time'),
    path('occupied-time/<int:occupied_id>/delete/', views.delete_occupied_time, name='delete_occupied_time'),

    # Quick Block
    path('quick-block/<int:occupied_id>/delete/', views.delete_quick_block, name='delete_quick_block'),

    # AJAX
    path('api/professor/<int:professor_id>/blocks/', views.api_professor_blocks, name='api_professor_blocks'),

    # Generate & view (legacy + smart)
    path('generate/', views.generate_timetable, name='generate'),
    path('generate-smart/', views.generate_timetable_smart, name='generate_smart'),
    path('timetable/<int:section_id>/', views.section_timetable, name='section_timetable'),
    path('timeslot/<int:timeslot_id>/edit/', views.edit_timeslot, name='edit_timeslot'),
    path('timetable/<int:section_id>/pdf/', views.export_pdf, name='export_pdf'),
    path('timetable/<int:section_id>/qr/', views.qr_timetable, name='qr_timetable'),
    path('timetable/<int:section_id>/csv/', views.export_timetable_csv, name='export_section_csv'),

    # Year timetable
    path('year-timetable/<int:course_id>/<str:year>/', views.year_timetable, name='year_timetable'),
    path('year-timetable/<int:course_id>/<str:year>/pdf/', views.export_year_pdf, name='export_year_pdf'),

    # Section combined timetable (G1+G2)
    path('section-timetable/<int:course_id>/<str:year>/<str:section_name>/', views.section_combined_timetable, name='section_combined_timetable'),
    path('section-timetable/<int:course_id>/<str:year>/<str:section_name>/pdf/', views.export_section_combined_pdf, name='export_section_combined_pdf'),

    # CSV Upload & Templates
    path('csv-upload/', views.csv_upload, name='csv_upload'),
    path('csv-template/<str:template_name>/', views.csv_download_template, name='csv_download_template'),
    # Dedicated Excel route — more reliable than a ?format= query string in browsers.
    path('csv-template/<str:template_name>/<str:fmt>/', views.csv_download_template, name='csv_download_template_fmt'),

    # Combine Edit
    path('combine-edit/', views.combine_edit, name='combine_edit'),
    path('combine-edit/save/', views.combine_edit_save, name='combine_edit_save'),
    path('combine-edit/export-csv/', views.combine_edit_export_csv, name='combine_edit_export_csv'),

    # Workload Report
    path('workload-report/', views.workload_report, name='workload_report'),
    path('workload-report/csv/', views.workload_report_csv, name='workload_report_csv'),

    # Timetable validation (conflict report)
    path('validate-timetable/', views.validate_timetable, name='validate_timetable'),

    # ── FREE ROOMS & LABS (add-on module) ──────────────────────────────────
    path('free-rooms/', views.free_rooms, name='free_rooms'),
    path('free-rooms/pdf/', views.free_rooms_pdf, name='free_rooms_pdf'),

    # ── FREE STUDENTS (Dean view) ──────────────────────────────────────────
    path('free-students/', views.free_students, name='free_students'),
]
