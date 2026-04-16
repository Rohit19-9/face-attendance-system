from django.contrib import admin
from .models import Employee, AttendanceRecord

@admin.register(Employee)
class EmpAdmin(admin.ModelAdmin):
    list_display  = ['emp_code', 'employee_name', 'user', 'is_face_registered', 'face_samples_count', 'created_at']
    search_fields = ['emp_code', 'employee_name', 'user__username']
    list_filter   = ['user', 'is_face_registered']

@admin.register(AttendanceRecord)
class AttAdmin(admin.ModelAdmin):
    list_display  = ['employee', 'date', 'check_in_time', 'check_out_time', 'status', 'confidence']
    list_filter   = ['status', 'date', 'employee__user']
    date_hierarchy = 'date'

admin.site.site_header = "Attendance System"
admin.site.site_title  = "Attendance System"
