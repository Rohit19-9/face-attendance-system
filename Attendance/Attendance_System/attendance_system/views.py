import json, cv2, numpy as np, pickle, os
from datetime import date, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.contrib import messages
from datetime import datetime as dt_now
from django.db.models import Q
from django.core.files.base import ContentFile

from .models import Employee, FaceSample, AttendanceRecord
from utils.face_engine import (get_liveness, get_engine, reload_engine,
                                reset_liveness, decode_b64, quality_check)

# In-memory store for face samples before DB save
# { session_key: { 'samples': {1: bytes, 2: bytes...} } }
_temp_store = {}


# ── AUTH ──────────────────────────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        u = authenticate(request,
                         username=request.POST.get('username', ''),
                         password=request.POST.get('password', ''))
        if u and u.is_active:
            login(request, u)
            return redirect('dashboard')
        messages.error(request, 'Invalid username or password.')
    return render(request, 'auth/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


# ── DASHBOARD ─────────────────────────────────────────────────────────────────
@login_required
def dashboard(request):
    today  = dt_now.now().date()
    total  = Employee.objects.filter(user=request.user, is_active=True).count()
    reg    = Employee.objects.filter(user=request.user, is_active=True, is_face_registered=True).count()
    present = AttendanceRecord.objects.filter(
        employee__user=request.user, date=today, status='present').count()
    absent = max(0, total - present)
    recent = AttendanceRecord.objects.filter(
        employee__user=request.user, date=today
    ).select_related('employee').order_by('-check_in_time')[:20]

    weekly = []
    for i in range(7):
        d = today - timedelta(days=6 - i)
        c = AttendanceRecord.objects.filter(employee__user=request.user, date=d).count()
        weekly.append({'day': d.strftime('%a'), 'count': c})

    return render(request, 'dashboard/dashboard.html', {
        'total': total, 'registered': reg,
        'present': present, 'absent': absent,
        'recent': recent, 'weekly': json.dumps(weekly),
        'today': today,
        'rate': round(present / total * 100 if total else 0, 1),
    })


# ── EMPLOYEES ─────────────────────────────────────────────────────────────────
@login_required
def employee_list(request):
    emps = Employee.objects.filter(user=request.user, is_active=True)
    q = request.GET.get('q', '')
    if q:
        emps = emps.filter(Q(emp_code__icontains=q) | Q(employee_name__icontains=q))
    return render(request, 'registration/employee_list.html', {'employees': emps, 'q': q})


@login_required
def add_employee(request):
    """Show form only — no DB save here at all."""
    return render(request, 'registration/add_employee.html')


# ── API: VALIDATE (check duplicate before opening camera) ────────────────────
@login_required
@csrf_exempt
def api_validate(request):
    """Validate emp_code + name. Return ok/error. NO DB save."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'msg': 'Method not allowed'})
    try:
        data = json.loads(request.body)
        code = data.get('emp_code', '').strip().upper()
        name = data.get('employee_name', '').strip()

        if not code:
            return JsonResponse({'ok': False, 'msg': 'Employee code is required.'})
        if not name:
            return JsonResponse({'ok': False, 'msg': 'Employee name is required.'})
        if Employee.objects.filter(user=request.user, emp_code=code).exists():
            return JsonResponse({'ok': False, 'msg': f'Code "{code}" already exists in your account.'})

        # Clear any old temp data for this session
        sk = request.session.session_key
        if not sk:
            request.session.create()
            sk = request.session.session_key
        _temp_store[sk] = {'samples': {}, 'code': code, 'name': name}

        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'msg': str(e)})


# ── API: CAPTURE SAMPLE (in-memory only) ─────────────────────────────────────
@login_required
@csrf_exempt
def api_capture_temp(request):
    """Store frame in memory. NO file write. NO DB save."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'msg': 'Method not allowed'})
    try:
        sk = request.session.session_key
        if not sk or sk not in _temp_store:
            return JsonResponse({'ok': False, 'msg': 'Session expired. Please refresh.'})

        data = json.loads(request.body)
        num  = int(data.get('num', 1))

        frame = decode_b64(data.get('image', ''))
        if frame is None:
            return JsonResponse({'ok': False, 'msg': 'Invalid image'})

        ok, msg = quality_check(frame)
        if not ok:
            return JsonResponse({'ok': False, 'msg': msg})

        # Store compressed bytes in memory
        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        _temp_store[sk]['samples'][num] = buf.tobytes()

        total = len(_temp_store[sk]['samples'])
        return JsonResponse({'ok': True, 'total': total, 'num': num})

    except Exception as e:
        return JsonResponse({'ok': False, 'msg': str(e)})


# ── API: COMPLETE REGISTRATION (NOW save to DB) ───────────────────────────────
@login_required
@csrf_exempt
def api_register_final(request):
    """
    All 10 samples captured → now:
    1. Encode faces
    2. Create Employee in DB
    3. Save face encoding
    4. Clear temp memory
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'msg': 'Method not allowed'})
    try:
        sk = request.session.session_key
        if not sk or sk not in _temp_store:
            return JsonResponse({'ok': False, 'msg': 'Session expired. Please refresh.'})

        store = _temp_store[sk]
        code  = store.get('code', '')
        name  = store.get('name', '')
        samples = store.get('samples', {})

        if len(samples) < 10:
            return JsonResponse({'ok': False, 'msg': f'Need 10 samples. Got {len(samples)}.'})

        if not code or not name:
            return JsonResponse({'ok': False, 'msg': 'Employee details missing.'})

        # Double-check duplicate
        if Employee.objects.filter(user=request.user, emp_code=code).exists():
            del _temp_store[sk]
            return JsonResponse({'ok': False, 'msg': f'Code "{code}" already exists.'})

        # Load images from memory
        images = []
        for num in sorted(samples.keys()):
            arr = np.frombuffer(samples[num], np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                images.append(img)

        if len(images) < 5:
            return JsonResponse({'ok': False, 'msg': f'Only {len(images)} valid images. Try again.'})

        # Encode faces using face_recognition
        try:
            import face_recognition
            encodings = []
            for img in images:
                rgb  = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                locs = face_recognition.face_locations(rgb, model='hog')
                if locs:
                    encs = face_recognition.face_encodings(rgb, locs, num_jitters=2)
                    if encs:
                        encodings.append(encs[0])
        except ImportError:
            return JsonResponse({'ok': False, 'msg': 'face_recognition not installed.'})

        if len(encodings) < 3:
            return JsonResponse({'ok': False, 'msg': f'Only {len(encodings)} faces detected. Better lighting chahiye.'})

        # ── NOW SAVE TO DATABASE ──
        emp = Employee.objects.create(
            user=request.user,
            emp_code=code,
            employee_name=name,
            face_encoding=pickle.dumps(encodings),
            is_face_registered=True,
            face_samples_count=len(encodings),
        )

        # Save face samples to tbl_face_samples
        for num in sorted(samples.keys()):
            buf_bytes = samples[num]
            content_file = ContentFile(buf_bytes, name=f'{code}_s{num}.jpg')
            FaceSample.objects.create(
                employee=emp,
                sample_number=num,
                image=content_file,
                is_processed=True,
            )

        # Reload face engine for this user
        reload_engine(request.user.id)

        # Clear temp memory
        del _temp_store[sk]

        return JsonResponse({
            'ok': True,
            'msg': f'{name} registered successfully!',
        })

    except Exception as e:
        return JsonResponse({'ok': False, 'msg': str(e)})


# ── Old routes kept for standalone register_face page ─────────────────────────
@login_required
def register_face(request, emp_id):
    emp  = get_object_or_404(Employee, id=emp_id, user=request.user)
    done = FaceSample.objects.filter(employee=emp).count()
    angles = ["Front","Slightly Left","Slightly Right","Look Up","Look Down",
              "Far Left","Far Right","Smile","Neutral","Eyes Wide"]
    return render(request, 'registration/register_face.html', {
        'employee': emp, 'done': done, 'required': 10,
        'angles': json.dumps(angles),
    })


@login_required
@csrf_exempt
def api_capture(request, emp_id):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'msg': 'Method not allowed'})
    try:
        emp  = get_object_or_404(Employee, id=emp_id, user=request.user)
        data = json.loads(request.body)
        num  = data.get('num', 1)
        frame = decode_b64(data.get('image', ''))
        if frame is None:
            return JsonResponse({'ok': False, 'msg': 'Invalid image'})
        ok, msg = quality_check(frame)
        if not ok:
            return JsonResponse({'ok': False, 'msg': msg})
        _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        content = ContentFile(buf.tobytes(), name=f'{emp.emp_code}_s{num}.jpg')
        FaceSample.objects.update_or_create(
            employee=emp, sample_number=num,
            defaults={'image': content, 'is_processed': False}
        )
        total = FaceSample.objects.filter(employee=emp).count()
        return JsonResponse({'ok': True, 'total': total, 'num': num})
    except Exception as e:
        return JsonResponse({'ok': False, 'msg': str(e)})


@login_required
@csrf_exempt
def api_register_complete(request, emp_id):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'msg': 'Method not allowed'})
    try:
        emp     = get_object_or_404(Employee, id=emp_id, user=request.user)
        samples = FaceSample.objects.filter(employee=emp)
        if samples.count() < 10:
            return JsonResponse({'ok': False, 'msg': f'Need 10 samples. Got {samples.count()}.'})
        images = []
        for s in samples:
            img = cv2.imread(s.image.path)
            if img is not None:
                images.append(img)
                s.is_processed = True
                s.save()
        eng = get_engine(request.user.id)
        ok, msg = eng.register(emp, images)
        if ok:
            reload_engine(request.user.id)
            return JsonResponse({'ok': True, 'msg': msg, 'redirect': '/employees/'})
        return JsonResponse({'ok': False, 'msg': msg})
    except Exception as e:
        return JsonResponse({'ok': False, 'msg': str(e)})


# ── ATTENDANCE ────────────────────────────────────────────────────────────────
@login_required
def mark_attendance(request):
    today   = dt_now.now().date()
    records = AttendanceRecord.objects.filter(
        employee__user=request.user, date=today
    ).select_related('employee').order_by('-check_in_time')
    return render(request, 'attendance/mark_attendance.html', {
        'records': records, 'today': today,
    })


@login_required
@csrf_exempt
def api_attendance(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'msg': 'Method not allowed'})
    try:
        data   = json.loads(request.body)
        frame  = decode_b64(data.get('image', ''))
        action = data.get('action', 'check_in')
        if frame is None:
            return JsonResponse({'ok': False, 'msg': 'Invalid image'})

        lv = get_liveness()
        is_live, score, msg, face_loc = lv.analyze(frame)
        if not is_live:
            return JsonResponse({'ok': False, 'stage': 'liveness', 'msg': msg, 'score': score})

        eng = get_engine(request.user.id)
        emp_id, name, conf, status = eng.recognize(frame, face_loc)

        if status != 'recognized':
            reset_liveness()
            return JsonResponse({'ok': False, 'stage': 'recognition',
                                 'msg': '❌ Face not recognized. Not registered!', 'conf': conf})

        try:
            emp = Employee.objects.get(id=emp_id, user=request.user)
        except Employee.DoesNotExist:
            reset_liveness()
            return JsonResponse({'ok': False, 'stage': 'recognition',
                                 'msg': '❌ Employee not found in your account.'})

        today = dt_now.now().date()
        now   = dt_now.now()
        existing = AttendanceRecord.objects.filter(employee=emp, date=today).first()

        if existing:
            if existing.check_out_time:
                reset_liveness()
                return JsonResponse({
                    'ok': False, 'stage': 'already_done', 'already': True,
                    'name': emp.employee_name, 'code': emp.emp_code,
                    'msg': f'⚠️ {emp.employee_name} already present & checked out today!',
                    'check_in':  existing.check_in_time.strftime('%I:%M %p') if existing.check_in_time else '-',
                    'check_out': existing.check_out_time.strftime('%I:%M %p'),
                })
            existing.check_out_time = now
            existing.save()
            reset_liveness()
            return JsonResponse({
                'ok': True, 'stage': 'done', 'action': 'check_out',
                'name': emp.employee_name, 'code': emp.emp_code,
                'conf': round(conf,1), 'score': round(score,1),
                'time': now.strftime('%I:%M:%S %p'), 'status': 'present',
                'msg': f'👋 {emp.employee_name} — Checked Out at {now.strftime("%I:%M %p")}',
            })

        AttendanceRecord.objects.create(
            user=request.user, employee=emp, date=today, status='present',
            liveness_ok=True, confidence=conf, check_in_time=now,
        )
        reset_liveness()
        return JsonResponse({
            'ok': True, 'stage': 'done', 'action': 'check_in',
            'name': emp.employee_name, 'code': emp.emp_code,
            'conf': round(conf,1), 'score': round(score,1),
            'time': now.strftime('%I:%M:%S %p'), 'status': 'present',
            'msg': f'✅ {emp.employee_name} — Checked In at {now.strftime("%I:%M %p")}',
        })

    except Exception as e:
        return JsonResponse({'ok': False, 'msg': str(e)})


# ── REPORT ────────────────────────────────────────────────────────────────────
@login_required
def report(request):
    today = dt_now.now().date()
    rd = request.GET.get('date', today.isoformat())
    try:
        rd = date.fromisoformat(rd)
    except Exception:
        rd = today
    records = AttendanceRecord.objects.filter(
        employee__user=request.user, date=rd
    ).select_related('employee')
    total   = Employee.objects.filter(user=request.user, is_active=True).count()
    present = records.filter(status='present').count()
    return render(request, 'attendance/report.html', {
        'records': records, 'report_date': rd,
        'total': total, 'present': present,
        'absent': max(0, total - present),
    })
