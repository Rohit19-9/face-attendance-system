********** face-attendance-system **********

STEP 1 - MySQL Workbench mein run karo:
  CREATE DATABASE face_attendance_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

STEP 2 - .env file mein password daalo:
  DB_PASSWORD=apna_mysql_password

STEP 3 - dlib model file:
  shape_predictor_68_face_landmarks.dat
  → ml_models\ folder mein rakho

  Download command (VS Code terminal):
  python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/italojs/facial-landmarks-recognition/raw/master/shape_predictor_68_face_landmarks.dat', 'ml_models/shape_predictor_68_face_landmarks.dat'); print('Done!')"

STEP 4 - SETUP.bat double click karo (sirf pehli baar)

STEP 5 - START_SERVER.bat double click karo (roz)

Browser: http://localhost:8000
Login:   admin / Admin@12345

********** NEW FEATURES IN THIS VERSION **********

✅ Add Employee:
   - Form + Camera SAME page par
   - Details fill karo → camera auto start
   - 10 samples capture → auto redirect

✅ Mark Attendance:
   - Camera pura area cover karta hai
   - Attendance mark hote hi camera AUTO OFF
   - 3 seconds baad AUTO RESTART (next person)
   - Already present → WARNING message in camera
   - Duplicate attendance BLOCKED

✅ Dashboard:
   - Late column removed
   - Only Present / Absent

✅ Anti-Spoofing:
   - Phone photo → BLOCKED
   - Printed photo → BLOCKED
   - Loop video → BLOCKED
   - Screen display → BLOCKED


 ********** DATABASE TABLES **********
 
  tbl_employees    → emp_code + employee_name
  tbl_face_samples → 10 images per employee
  tbl_attendance   → daily records

