"""
FaceGuard Pro — Advanced Face Engine
User-aware: loads only current user's employee faces
CNN ResNet-34 + DNN 68-point + 5-layer Anti-Spoofing
No photo storage in attendance
"""
import cv2, numpy as np, pickle, os
from collections import deque

try:
    import face_recognition
    FR = True
except ImportError:
    FR = False

try:
    import dlib
    from imutils import face_utils
    from scipy.spatial import distance as dist
    DL = True
except ImportError:
    DL = False

from django.conf import settings


def ear(eye):
    A = dist.euclidean(eye[1], eye[5])
    B = dist.euclidean(eye[2], eye[4])
    C = dist.euclidean(eye[0], eye[3])
    return (A + B) / (2.0 * C)


class AntiSpoof:
    @staticmethod
    def texture(roi):
        if roi is None or roi.size == 0: return False, 0.0
        g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        g = cv2.resize(g, (64, 64))
        lap = cv2.Laplacian(g, cv2.CV_64F).var()
        return lap > 4.5, min(100.0, float(lap))

    @staticmethod
    def reflection(roi):
        if roi is None or roi.size == 0: return True, 80.0
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        v = hsv[:, :, 2].astype(float)
        s = hsv[:, :, 1].astype(float)
        br = (v > 240).sum() / (roi.shape[0] * roi.shape[1] + 1e-7)
        if br > 0.15: return False, 0.0
        if np.std(s) < 8 and np.std(v) < 10: return False, 20.0
        return True, min(100.0, float(np.std(s) * 2 + np.std(v) * 1.5))

    @staticmethod
    def color_var(roi):
        if roi is None or roi.size == 0: return True, 80.0
        b, g, r = cv2.split(roi.astype(float))
        diff = np.mean(np.abs(r-g)) + np.mean(np.abs(r-b)) + np.mean(np.abs(g-b))
        if diff < 8: return False, 10.0
        return np.mean(r) > np.mean(b), min(100.0, float(diff * 3))

    @staticmethod
    def frequency(roi):
        if roi is None or roi.size == 0: return True, 80.0
        g = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        g = cv2.resize(g, (64, 64)).astype(np.float32)
        mag = np.log1p(np.abs(np.fft.fftshift(np.fft.fft2(g))))
        h, w = mag.shape; cy, cx = h//2, w//2
        ratio = np.sum(mag[cy-8:cy+8, cx-8:cx+8]) / (np.sum(mag) + 1e-7)
        if ratio > 0.92: return False, 20.0
        if ratio < 0.30: return False, 30.0
        return True, float(max(0, 100 - abs(ratio - 0.65) * 200))

    @classmethod
    def run(cls, roi):
        checks = [
            (cls.texture(roi),    0.35),
            (cls.reflection(roi), 0.30),
            (cls.color_var(roi),  0.20),
            (cls.frequency(roi),  0.15),
        ]
        score = sum(w * r[1] for r, w in checks)
        fails = sum(1 for r, _ in checks if not r[0])
        if fails >= 2: return min(score, 28.0), True
        return min(score, 100.0), False


class LivenessDetector:
    def __init__(self):
        self.EAR_T   = 0.22
        self.EAR_C   = 2
        self.BLINKS  = 2
        self.SPOOF_T = 50.0
        self.prev_g  = None
        self.mot_buf = deque(maxlen=15)
        self.sp_buf  = deque(maxlen=10)
        self.reset()
        self._load()

    def _load(self):
        self.ready = False
        if not DL: return
        self.det = dlib.get_frontal_face_detector()
        p = os.path.join(settings.BASE_DIR, 'ml_models', 'shape_predictor_68_face_landmarks.dat')
        if os.path.exists(p):
            self.pred = dlib.shape_predictor(p)
            self.ready = True
            (self.lS, self.lE) = face_utils.FACIAL_LANDMARKS_IDXS["left_eye"]
            (self.rS, self.rE) = face_utils.FACIAL_LANDMARKS_IDXS["right_eye"]

    def reset(self):
        self.blink_c = 0
        self.blinks  = 0
        self.score   = 0.0
        self.mot_c   = 0
        self.frames  = 0
        self.sp_buf.clear()
        self.mot_buf.clear()
        self.prev_g  = None

    def _motion(self, frame):
        g = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (80, 60))
        g = cv2.GaussianBlur(g, (5, 5), 0)
        if self.prev_g is not None:
            diff = np.mean(cv2.absdiff(self.prev_g, g))
            self.mot_buf.append(diff)
            avg = np.mean(self.mot_buf)
            if 0.4 < avg < 14: self.mot_c = min(self.mot_c + 1, 25)
            elif avg <= 0.4:    self.mot_c = max(0, self.mot_c - 1)
        self.prev_g = g.copy()
        return self.mot_c

    def analyze(self, frame):
        self.frames += 1
        mot = self._motion(frame)
        if not self.ready:
            return self._basic(frame, mot)

        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        rects = self.det(gray, 0)
        if not rects:
            return False, 0.0, "👤 Camera ke saamne aayein", None
        if len(rects) > 1:
            return False, 0.0, "⚠️ Ek hi person allowed", None

        rect = rects[0]
        x1 = max(0, rect.left());  y1 = max(0, rect.top())
        x2 = min(frame.shape[1], rect.right()); y2 = min(frame.shape[0], rect.bottom())
        roi = frame[y1:y2, x1:x2]

        sp, spoofed = AntiSpoof.run(roi)
        self.sp_buf.append(sp)
        avg_sp = float(np.mean(self.sp_buf))
        loc = (rect.top(), rect.right(), rect.bottom(), rect.left())

        if spoofed and avg_sp < self.SPOOF_T and self.frames > 8:
            return False, avg_sp, "🚫 FAKE FACE! Live camera use karein", loc

        shape = self.pred(gray, rect)
        snp   = face_utils.shape_to_np(shape)
        e_val = (ear(snp[self.lS:self.lE]) + ear(snp[self.rS:self.rE])) / 2.0

        if e_val < self.EAR_T: self.blink_c += 1
        else:
            if self.blink_c >= self.EAR_C: self.blinks += 1
            self.blink_c = 0

        s  = min(40, avg_sp * 0.40)
        s += min(35, self.blinks * 17)
        s += min(15, mot * 1.5)
        s += 10 if self.frames > 5 else 0
        self.score = min(s, 100.0)

        left = max(0, self.BLINKS - self.blinks)
        if avg_sp < self.SPOOF_T and self.frames > 8:
            return False, self.score, "🚫 Fake face! Live camera use karein", loc
        if left > 0:
            return False, self.score, f"👁️ Blink {left} more time(s)", loc
        if self.score >= 65:
            return True, self.score, "✅ Live human verified!", loc
        return False, self.score, "🔄 Hold still...", loc

    def _basic(self, frame, mot):
        if not FR: return True, 80.0, "✅ Ready", None
        locs = face_recognition.face_locations(frame)
        if not locs: return False, 0.0, "👤 Camera ke saamne aayein", None
        if len(locs) > 1: return False, 0.0, "⚠️ Ek hi person", None
        t, r, b, l = locs[0]
        sp, spoofed = AntiSpoof.run(frame[t:b, l:r])
        self.sp_buf.append(sp)
        avg = float(np.mean(self.sp_buf))
        if spoofed and avg < self.SPOOF_T and self.frames > 6:
            return False, avg, "🚫 Fake face!", locs[0]
        s = min(100, avg * 0.7 + mot * 3)
        return (True, s, "✅ Live!", locs[0]) if s >= 60 else (False, s, "👁️ Analyzing...", locs[0])


class FaceEngine:
    """
    User-aware Face Engine.
    Loads only the faces belonging to the current user.
    Each user has their own isolated face database.
    """
    def __init__(self, user_id=None):
        self.encs  = []
        self.ids   = []
        self.names = []
        self.user_id = user_id
        self.TOL   = getattr(settings, 'FACE_RECOGNITION_TOLERANCE', 0.45)
        self.load(user_id)

    def load(self, user_id=None):
        if not FR: return
        try:
            from attendance_system.models import Employee
            qs = Employee.objects.filter(is_face_registered=True, is_active=True, face_encoding__isnull=False)
            # Filter by user if provided
            if user_id:
                qs = qs.filter(user_id=user_id)
            self.encs  = []
            self.ids   = []
            self.names = []
            for emp in qs:
                if emp.face_encoding:
                    lst = pickle.loads(bytes(emp.face_encoding))
                    for e in (lst if isinstance(lst, list) else [lst]):
                        self.encs.append(e)
                        self.ids.append(emp.id)
                        self.names.append(emp.employee_name)
            print(f"✅ Loaded {len(self.encs)} encodings for user_id={user_id}")
        except Exception as ex:
            print(f"Load error: {ex}")

    def encode(self, img):
        if not FR: return None, "unavailable"
        try:
            rgb  = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            locs = face_recognition.face_locations(rgb, model="hog")
            if not locs: return None, "No face"
            encs = face_recognition.face_encodings(rgb, locs, num_jitters=3)
            return (encs[0], "OK") if encs else (None, "Encode fail")
        except Exception as ex:
            return None, str(ex)

    def recognize(self, frame, loc=None):
        if not FR: return None, "Unknown", 0.0, "unavailable"
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if not loc:
                locs = face_recognition.face_locations(rgb)
                if not locs: return None, "Unknown", 0.0, "no_face"
                loc = locs[0]
            encs = face_recognition.face_encodings(rgb, [loc])
            if not encs: return None, "Unknown", 0.0, "no_enc"
            if not self.encs: return None, "Unknown", 0.0, "empty_db"
            dists = face_recognition.face_distance(self.encs, encs[0])
            i = np.argmin(dists); d = dists[i]
            conf = (1 - d) * 100
            return (self.ids[i], self.names[i], conf, "recognized") if d <= self.TOL else (None, "Unknown", conf, "not_recognized")
        except Exception as ex:
            return None, "Error", 0.0, str(ex)

    def register(self, emp, images):
        encs = [e for img in images for e, _ in [self.encode(img)] if e is not None]
        if len(encs) < 5:
            return False, f"Only {len(encs)} valid. Need 5+"
        emp.face_encoding      = pickle.dumps(encs)
        emp.is_face_registered = True
        emp.face_samples_count = len(encs)
        emp.save()
        self.load(self.user_id)
        return True, f"✅ Registered {len(encs)} encodings!"


def decode_b64(b64):
    import base64
    return cv2.imdecode(np.frombuffer(base64.b64decode(b64.split(',')[1]), np.uint8), cv2.IMREAD_COLOR)


def quality_check(frame):
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if cv2.Laplacian(g, cv2.CV_64F).var() < 35: return False, "Too blurry"
    m = np.mean(g)
    if m < 30:  return False, "Too dark"
    if m > 230: return False, "Too bright"
    if FR and not face_recognition.face_locations(frame): return False, "No face"
    return True, "OK"


# ── Per-user engine cache ──────────────────────────────────────────────────────
_engines = {}   # {user_id: FaceEngine}
_lv_inst = None


def get_engine(user_id):
    """Return or create a FaceEngine scoped to this user."""
    if user_id not in _engines:
        _engines[user_id] = FaceEngine(user_id=user_id)
    return _engines[user_id]


def reload_engine(user_id):
    """Reload after new employee registered."""
    _engines[user_id] = FaceEngine(user_id=user_id)


def get_liveness():
    global _lv_inst
    if _lv_inst is None:
        _lv_inst = LivenessDetector()
    return _lv_inst


def reset_liveness():
    global _lv_inst
    if _lv_inst:
        _lv_inst.reset()
