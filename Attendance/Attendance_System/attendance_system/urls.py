from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path("", views.login_view, name="login"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # Dashboard
    path("dashboard/", views.dashboard, name="dashboard"),

    # Employees
    path("employees/", views.employee_list, name="employee_list"),
    path("employees/add/", views.add_employee, name="add_employee"),
    path("employees/<int:emp_id>/register/", views.register_face, name="register_face"),

    # New APIs — no DB save until registration complete
    path("api/validate/", views.api_validate, name="api_validate"),
    path("api/capture-temp/", views.api_capture_temp, name="api_capture_temp"),
    path("api/register-final/", views.api_register_final, name="api_register_final"),

    # Old APIs (standalone register page)
    path("api/capture/<int:emp_id>/", views.api_capture, name="api_capture"),
    path("api/register/<int:emp_id>/", views.api_register_complete, name="api_register"),

    # Attendance
    path("attendance/", views.mark_attendance, name="mark_attendance"),
    path("api/attendance/", views.api_attendance, name="api_attendance"),

    # Report
    path("report/", views.report, name="report"),
]
