import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend import campus_model as m


# ---- Unit checks
def test_U1_high_high_is_M1():
    assert m.priority("High", "High") == "M1"

def test_U2_low_low_is_M4():
    assert m.priority("Low", "Low") == "M4"

def test_U3_impact_out_of_range():
    with pytest.raises(ValueError):
        m.priority("Critical", "High")

def test_U4_water_leak_is_facilities():
    assert m.classify("Water leak from lab ceiling") == "Facilities"

def test_U5_equal_evidence_manual():
    assert m.classify("leak and projector fault") == "Manual Review"

def test_U6_temperature_threshold():
    assert (m.breached(28.0), m.breached(28.01)) == (False, True)


# ---- Integration checks (real SQLite database)
def test_I1_commands_persist_and_audit(tmp_path):
    p = str(tmp_path / "campus.db")
    s = m.Store(p)
    t = s.create_ticket("AC compressor tripping in Lab 204")
    v = 1
    for target, notes in [
        ("Assigned", None),
        ("In Progress", None),
        ("Resolved", "Reset breaker"),
        ("Closed", None)
    ]:
        v = s.transition(t, target, v, "technician", notes)
    s.db.close()
    s2 = m.Store(p)          # close and reopen file database
    assert s2.state(t) == ("Closed", 5) and s2.audit_count(t) == 4

def test_I2_repeated_event_one_ticket():
    s = m.Store()
    ids = {s.create_ticket("Temp high", "sensor-7", "evt-1") for _ in range(5)}
    assert len(ids) == 1 and s.count() == 1

def test_I3_student_cannot_approve_booking():
    s = m.Store()
    b = s.request_booking("Lab-204", 600, 720)
    with pytest.raises(PermissionError):
        s.approve_booking(b, "student")
    assert s.booking_status(b) == "Pending"

def test_I4_overlap_rejected_adjacent_allowed():
    s = m.Store()
    s.request_booking("Lab-204", 600, 720)
    with pytest.raises(RuntimeError):
        s.request_booking("Lab-204", 700, 800)
    s.request_booking("Lab-204", 720, 800)  # back-to-back is allowed
    assert s.count("bookings") == 2


# ---- Regression checks (previously correct behaviour)
def test_R1_high_medium_is_M2():
    assert m.priority("High", "Medium") == "M2"

def test_R2_unknown_terms_manual():
    assert m.classify("strange noise somewhere") == "Manual Review"

def test_R3_resolve_without_notes_rejected():
    s = m.Store()
    t = s.create_ticket("Door lock jammed")
    s.transition(t, "Assigned", 1, "technician")
    s.transition(t, "In Progress", 2, "technician")
    with pytest.raises(ValueError):
        s.transition(t, "Resolved", 3, "technician", " ")
    assert s.state(t)[0] == "In Progress"

def test_R4_stale_version_rejected():
    s = m.Store()
    t = s.create_ticket("Display flicker")
    s.transition(t, "Assigned", 1, "technician")
    with pytest.raises(RuntimeError):
        s.transition(t, "In Progress", 1, "technician")
    assert s.state(t) == ("Assigned", 2)