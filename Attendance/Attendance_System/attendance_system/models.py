from django.db import models
from django.contrib.auth.models import User
from datetime import date as dt_date


class Employee(models.Model):
    """
    Employee — belongs to a specific User.
    emp_code unique per user only.
    face_encoding stored directly in this table.
    NO FaceSample table — samples stored in memory only during registration.
    """
    user               = models.ForeignKey(User, on_delete=models.CASCADE, related_name='employees')
    emp_code           = models.CharField(max_length=20, db_index=True)
    employee_name      = models.CharField(max_length=100)
    is_face_registered = models.BooleanField(default=False)
    face_encoding      = models.BinaryField(null=True, blank=True)
    face_samples_count = models.IntegerField(default=0)
    created_at         = models.DateTimeField(auto_now_add=True)
    is_active          = models.BooleanField(default=True)

    class Meta:
        db_table     = 'tbl_employees'
        ordering     = ['emp_code']
        unique_together = [('user', 'emp_code')]

    def __str__(self):
        return f"{self.emp_code} - {self.employee_name} [{self.user.username}]"




class FaceSample(models.Model):
    """10 face sample images per employee — saved after registration complete"""
    employee      = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='face_samples')
    sample_number = models.IntegerField()
    image         = models.ImageField(upload_to='photos/samples/')
    is_processed  = models.BooleanField(default=False)
    captured_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table        = 'tbl_face_samples'
        unique_together = [('employee', 'sample_number')]

    def __str__(self):
        return f"{self.employee.emp_code} - Sample {self.sample_number}"

class AttendanceRecord(models.Model):
    """Daily attendance — no photo stored."""
    STATUS = [('present', 'Present'), ('absent', 'Absent')]

    user           = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attendance', null=True, blank=True)
    employee       = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance')
    date           = models.DateField(default=dt_date.today, db_index=True)
    check_in_time  = models.DateTimeField(null=True, blank=True)
    check_out_time = models.DateTimeField(null=True, blank=True)
    status         = models.CharField(max_length=10, choices=STATUS, default='present')
    confidence     = models.FloatField(default=0.0)
    liveness_ok    = models.BooleanField(default=False)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table        = 'tbl_attendance'
        unique_together = [('employee', 'date')]
        ordering        = ['-date', '-check_in_time']

    def __str__(self):
        return f"{self.employee.emp_code} - {self.date}"

    @property
    def working_hours(self):
        if self.check_in_time and self.check_out_time:
            delta = self.check_out_time - self.check_in_time
            h = delta.seconds // 3600
            m = (delta.seconds % 3600) // 60
            return f"{h}h {m}m"
        return "-"
