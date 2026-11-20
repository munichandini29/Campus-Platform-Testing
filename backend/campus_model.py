"""Compact test model of core campus-platform rules (Python + SQLite).
It is narrower than the full application: no HTTP, tokens or external services."""
import sqlite3

MATRIX = {
    ("High", "High"): "M1", ("High", "Medium"): "M2", ("High", "Low"): "M3",
    ("Medium", "High"): "M2", ("Medium", "Medium"): "M3", ("Medium", "Low"): "M4",
    ("Low", "High"): "M3", ("Low", "Medium"): "M4", ("Low", "Low"): "M4"
}

KEYWORDS = {
    "Facilities": ["leak", "flood", "ceiling", "door", "lock"],
    "HVAC": ["ac", "compressor", "temperature", "cooling"],
    "AV-Network": ["projector", "display", "wifi", "network"]
}

MAX_MINUTES = 180
TEMP_LIMIT = 28.0

TRANSITIONS = {
    "New": ["Assigned"],
    "Assigned": ["In Progress"],
    "In Progress": ["Resolved"],
    "Resolved": ["Closed"],
    "Closed": []
}

STAFF = {"technician", "manager"}
APPROVERS = {"approver", "manager"}


def priority(impact, urgency):
    if (impact, urgency) not in MATRIX:
        raise ValueError("invalid matrix input")
    return MATRIX[(impact, urgency)]


def classify(text):
    words = text.lower().replace(",", " ").split()
    scores = {c: sum(1 for w in words if w in kws) for c, kws in KEYWORDS.items()}
    best = max(scores.values())
    top = [c for c, s in scores.items() if s == best]
    if best == 0 or len(top) != 1:
        return "Manual Review"
    return top[0]


def breached(value):
    return value > TEMP_LIMIT   # TEMP_LIMIT = 28.0


def valid_duration(minutes):
    return 0 < minutes <= MAX_MINUTES


def overlaps(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1   # half-open: back-to-back is allowed


class Store:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            state TEXT NOT NULL,
            version INTEGER NOT NULL,
            notes TEXT,
            source TEXT,
            event_id TEXT,
            UNIQUE(source, event_id)
        );
        CREATE TABLE IF NOT EXISTS audit(
            id INTEGER PRIMARY KEY,
            ticket_id INTEGER,
            from_state TEXT,
            to_state TEXT,
            actor TEXT
        );
        CREATE TABLE IF NOT EXISTS bookings(
            id INTEGER PRIMARY KEY,
            facility TEXT,
            start_min INTEGER,
            end_min INTEGER,
            status TEXT
        );
        """)

    def create_ticket(self, title, source=None, event_id=None):
        if not title or not title.strip():
            raise ValueError("title required")
        if source is not None:
            row = self.db.execute(
                "SELECT id FROM tickets WHERE source=? AND event_id=?",
                (source, event_id)
            ).fetchone()
            if row:
                return row[0]
        cur = self.db.execute(
            "INSERT INTO tickets(title, state, version, source, event_id) VALUES (?,?,?,?,?)",
            (title, "New", 1, source, event_id)
        )
        self.db.commit()
        return cur.lastrowid

    def count(self, table="tickets"):
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def state(self, tid):
        return self.db.execute(
            "SELECT state, version FROM tickets WHERE id=?", (tid,)
        ).fetchone()

    def transition(self, tid, target, expected_version, role, notes=None):
        if role not in STAFF:
            raise PermissionError("role not permitted")
        state, version = self.state(tid)
        if target not in TRANSITIONS[state]:
            raise ValueError(f"invalid transition {state} -> {target}")
        if target == "Resolved" and not (notes and notes.strip()):
            raise ValueError("resolution notes required")
        cur = self.db.execute(
            "UPDATE tickets SET state=?, version=version+1, notes=COALESCE(?,notes) "
            "WHERE id=? AND version=?",
            (target, notes, tid, expected_version)
        )
        if cur.rowcount != 1:
            self.db.rollback()
            raise RuntimeError("stale version")
        self.db.execute(
            "INSERT INTO audit(ticket_id, from_state, to_state, actor) VALUES (?,?,?,?)",
            (tid, state, target, role)
        )
        self.db.commit()
        return version + 1

    def audit_count(self, tid):
        return self.db.execute(
            "SELECT COUNT(*) FROM audit WHERE ticket_id=?", (tid,)
        ).fetchone()[0]

    def request_booking(self, facility, start, end):
        if not valid_duration(end - start):
            raise ValueError("duration outside policy")
        for s, e in self.db.execute(
            "SELECT start_min, end_min FROM bookings WHERE facility=? AND status='Pending'",
            (facility,)
        ):
            if overlaps(start, end, s, e):
                raise RuntimeError("overlapping booking")
        cur = self.db.execute(
            "INSERT INTO bookings(facility, start_min, end_min, status) VALUES (?,?,?,'Pending')",
            (facility, start, end)
        )
        self.db.commit()
        return cur.lastrowid

    def approve_booking(self, bid, role):
        if role not in APPROVERS:
            raise PermissionError("role not permitted")
        self.db.execute("UPDATE bookings SET status='Approved' WHERE id=?", (bid,))
        self.db.commit()

    def booking_status(self, bid):
        return self.db.execute(
            "SELECT status FROM bookings WHERE id=?", (bid,)
        ).fetchone()[0]