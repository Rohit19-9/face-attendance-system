from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    def handle(self, *args, **options):
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin','admin@faceguard.com','Admin@12345')
            self.stdout.write(self.style.SUCCESS('✓ Admin: admin / Admin@12345'))
        else:
            self.stdout.write('Admin already exists.')
        self.stdout.write(self.style.SUCCESS('✓ Done! Open: http://localhost:8000'))
