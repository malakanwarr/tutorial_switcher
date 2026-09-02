"""
test_everything.py

Comprehensive pre-launch test suite. Covers every business rule and every
bug we found and fixed along the way — not just "does matching work,"
but "does every constraint actually hold, and do the specific failure
modes we hit in development stay fixed."

Safe to run against your real production DB — every test uses student_ids
prefixed with TEST-, notify.py already skips sending real emails to any
batch containing a TEST- id, and every test cleans up after itself.

Usage:
    cd backend
    python test_everything.py
"""

from datetime import datetime, timedelta
from db import get_db_connection
from matching import run_matching_engine, cleanup_ghost_matches

PASS = "✅"
FAIL = "❌"
results = []


def record(name, condition):
    status = PASS if condition else FAIL
    results.append((name, condition))
    print(f"{status} {name}")
    return condition


def clear_test_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM matches WHERE student_id LIKE 'TEST-%'")
    cursor.execute("DELETE FROM desired_slots WHERE student_id LIKE 'TEST-%'")
    cursor.execute("DELETE FROM students WHERE student_id LIKE 'TEST-%'")
    conn.commit()
    cursor.close()
    conn.close()


def inject_test_student(student_id, email, major, semester, current_slot, desired_slots,
                         english_level=None, german_level=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    batch = student_id.split('-')[1]

    cursor.execute("""
        INSERT INTO students (student_id, whatsapp_number, university_email, major, semester,
                               batch, current_tutorial, english_level, german_level, is_matched)
        VALUES (%s, '+201000000000', %s, %s, %s, %s, %s, %s, %s, FALSE)
    """, (student_id, email, major, semester, batch, current_slot, english_level, german_level))

    for priority, slot in enumerate(desired_slots):
        cursor.execute("""
            INSERT INTO desired_slots (student_id, tutorial_id, priority)
            VALUES (%s, %s, %s)
        """, (student_id, slot, priority))

    conn.commit()
    cursor.close()
    conn.close()


def check_is_matched(student_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_matched FROM students WHERE student_id = %s", (student_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None


def get_match_group(student_id):
    """Returns the match_group_id + status a student is currently in, or None."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT match_group_id, status FROM matches
        WHERE student_id = %s AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
    """, (student_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_group_members(match_group_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT student_id FROM matches WHERE match_group_id = %s", (match_group_id,))
    ids = {r[0] for r in cursor.fetchall()}
    cursor.close()
    conn.close()
    return ids


def simulate_flake(student_id):
    """Mirrors exactly what /flake-swap does: cancels the WHOLE group and frees everyone."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT match_group_id FROM matches WHERE student_id = %s AND status = 'pending'", (student_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return None
    match_group_id = row[0]
    cursor.execute("UPDATE matches SET status = 'cancelled' WHERE match_group_id = %s", (match_group_id,))
    cursor.execute("""
        UPDATE students SET is_matched = FALSE
        WHERE student_id IN (SELECT student_id FROM matches WHERE match_group_id = %s)
    """, (match_group_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return match_group_id


def backdate_match(match_group_id, hours_ago):
    """Simulates an old, ignored match by rewriting created_at into the past."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE matches SET created_at = %s WHERE match_group_id = %s",
        (datetime.utcnow() - timedelta(hours=hours_ago), match_group_id)
    )
    conn.commit()
    cursor.close()
    conn.close()


def run_all_tests():
    print("Clearing old test data...\n")
    clear_test_data()

    # ==========================================================
    # TEST 1: Walled Garden — Major Mismatch
    # ==========================================================
    print("TEST 1: Walled Garden (different majors must not match)")
    inject_test_student("TEST-61-1", "t1@x.com", "MET", 7, 10, [11])
    inject_test_student("TEST-61-2", "t2@x.com", "CSEN", 7, 11, [10])
    run_matching_engine()
    record("Different majors correctly NOT matched",
           not check_is_matched("TEST-61-1") and not check_is_matched("TEST-61-2"))
    clear_test_data()

    # ==========================================================
    # TEST 2: Walled Garden — Batch Mismatch
    # ==========================================================
    print("\nTEST 2: Walled Garden (different batches must not match)")
    inject_test_student("TEST-61-3", "t3@x.com", "MET", 7, 12, [13])
    inject_test_student("TEST-62-4", "t4@x.com", "MET", 7, 13, [12])
    run_matching_engine()
    record("Different batches correctly NOT matched",
           not check_is_matched("TEST-61-3") and not check_is_matched("TEST-62-4"))
    clear_test_data()

    # ==========================================================
    # TEST 3: Language Mismatch Blocks Match (semester <= 4)
    # ==========================================================
    print("\nTEST 3: Language constraint blocks mismatched underclassmen")
    inject_test_student("TEST-61-5", "t5@x.com", "CSEN", 2, 14, [15],
                         english_level="B1", german_level="A2")
    inject_test_student("TEST-61-6", "t6@x.com", "CSEN", 2, 15, [14],
                         english_level="B2", german_level="A2")
    run_matching_engine()
    record("Mismatched language levels correctly NOT matched",
           not check_is_matched("TEST-61-5") and not check_is_matched("TEST-61-6"))
    clear_test_data()

    # ==========================================================
    # TEST 4: Language Match Allows Trade (semester <= 4)
    # ==========================================================
    print("\nTEST 4: Matching language levels allow a trade")
    inject_test_student("TEST-61-7", "t7@x.com", "CSEN", 2, 16, [17],
                         english_level="B1", german_level="A2")
    inject_test_student("TEST-61-8", "t8@x.com", "CSEN", 2, 17, [16],
                         english_level="B1", german_level="A2")
    run_matching_engine()
    record("Identical language levels correctly matched",
           check_is_matched("TEST-61-7") and check_is_matched("TEST-61-8"))
    clear_test_data()

    # ==========================================================
    # TEST 5: Upperclassmen Ignore Language Entirely
    # ==========================================================
    print("\nTEST 5: Semester > 4 ignores language levels")
    inject_test_student("TEST-61-9", "t9@x.com", "CSEN", 6, 18, [19],
                         english_level="B1", german_level="A2")
    inject_test_student("TEST-61-10", "t10@x.com", "CSEN", 6, 19, [18],
                         english_level="C1", german_level="B1")
    run_matching_engine()
    record("Upperclassmen matched despite different language levels",
           check_is_matched("TEST-61-9") and check_is_matched("TEST-61-10"))
    clear_test_data()

    # ==========================================================
    # TEST 6: Standard 2-Way Match
    # ==========================================================
    print("\nTEST 6: Standard 2-way match")
    inject_test_student("TEST-61-11", "t11@x.com", "MET", 7, 20, [21])
    inject_test_student("TEST-61-12", "t12@x.com", "MET", 7, 21, [20])
    run_matching_engine()
    record("Standard 2-way trade matched", check_is_matched("TEST-61-11") and check_is_matched("TEST-61-12"))
    clear_test_data()

    # ==========================================================
    # TEST 7: Preference Priority — 1st choice wins over 2nd choice
    # ==========================================================
    print("\nTEST 7: Preference priority (1st choice preferred over 2nd)")
    # X wants Y1's slot (1st choice) or Y2's slot (2nd choice)
    inject_test_student("TEST-61-13", "tx@x.com", "MET", 7, 100, [101, 102])
    inject_test_student("TEST-61-14", "ty1@x.com", "MET", 7, 101, [100])  # 1st choice partner
    inject_test_student("TEST-61-15", "ty2@x.com", "MET", 7, 102, [100])  # 2nd choice partner
    run_matching_engine()
    matched_with_first_choice = check_is_matched("TEST-61-14") and not check_is_matched("TEST-61-15")
    record("Student matched with 1st-choice partner over 2nd-choice", matched_with_first_choice)
    clear_test_data()

    # ==========================================================
    # TEST 8: 3-Way Trade
    # ==========================================================
    print("\nTEST 8: 3-way trade")
    inject_test_student("TEST-61-16", "t16@x.com", "MET", 7, 30, [31])
    inject_test_student("TEST-61-17", "t17@x.com", "MET", 7, 31, [32])
    inject_test_student("TEST-61-18", "t18@x.com", "MET", 7, 32, [30])
    run_matching_engine()
    record("3-way cycle matched",
           check_is_matched("TEST-61-16") and check_is_matched("TEST-61-17") and check_is_matched("TEST-61-18"))

    # ==========================================================
    # TEST 9: 3-Way Flake — Entire Group Returns to Pool
    # ==========================================================
    print("\nTEST 9: 3-way flake returns the WHOLE group (including the flaker)")
    group_id_9 = simulate_flake("TEST-61-18")
    record("All 3 members freed after one flakes",
           not check_is_matched("TEST-61-16") and not check_is_matched("TEST-61-17") and not check_is_matched("TEST-61-18"))

    # ==========================================================
    # TEST 10: Blacklist Prevents Instant Re-matching After a Flake
    # ==========================================================
    print("\nTEST 10: Blacklist prevents the exact same group re-matching immediately")
    run_matching_engine()  # same 3 students still mutually want each other — should NOT re-match
    record("Flaked group correctly NOT re-matched on the next run",
           not check_is_matched("TEST-61-16") and not check_is_matched("TEST-61-17") and not check_is_matched("TEST-61-18"))
    clear_test_data()

    # ==========================================================
    # TEST 11: Ghost Match Expiry After 24 Hours
    # ==========================================================
    print("\nTEST 11: Ignored matches expire after 24 hours and free both students")
    inject_test_student("TEST-61-19", "t19@x.com", "MET", 7, 40, [41])
    inject_test_student("TEST-61-20", "t20@x.com", "MET", 7, 41, [40])
    run_matching_engine()

    group = get_match_group("TEST-61-19")
    if group:
        match_group_id, _ = group
        backdate_match(match_group_id, hours_ago=25)  # simulate 25 hours of silence
        cleanup_ghost_matches(hours_to_wait=24)
        record("Ignored match expired and both students freed after 24h",
               not check_is_matched("TEST-61-19") and not check_is_matched("TEST-61-20"))
    else:
        record("Ignored match expired and both students freed after 24h", False)

    # ==========================================================
    # TEST 12: Expired Matches Also Get Blacklisted (the bug we fixed today)
    # ==========================================================
    print("\nTEST 12: Expired matches are blacklisted, not instantly re-matched")
    run_matching_engine()  # same two students, still mutually desiring each other
    record("Expired pair correctly NOT instantly re-matched",
           not check_is_matched("TEST-61-19") and not check_is_matched("TEST-61-20"))
    clear_test_data()

    # ==========================================================
    # SUMMARY
    # ==========================================================
    print("\n" + "=" * 50)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    if passed == total:
        print("🎉 All tests passed — the matching engine's core rules all hold.")
    else:
        print("⚠️ Some tests failed — DO NOT launch until these are fixed:")
        for name, ok in results:
            if not ok:
                print(f"   - {name}")
    print("=" * 50)

    clear_test_data()
    print("\nTest data cleaned up.")


if __name__ == "__main__":
    run_all_tests()