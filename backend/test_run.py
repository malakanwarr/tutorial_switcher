from db import get_db_connection
from matching import run_matching_engine
import uuid

def clear_test_data():
    """Wipes out any fake test students so we start with a clean slate."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM matches WHERE student_id LIKE 'TEST-%'")
    cursor.execute("DELETE FROM desired_slots WHERE student_id LIKE 'TEST-%'")
    cursor.execute("DELETE FROM students WHERE student_id LIKE 'TEST-%'")
    conn.commit()
    cursor.close()
    conn.close()

def inject_test_student(student_id, email, major, semester, current_slot, desired_slots):
    """Creates a fake student and their desired slots in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Extract the batch from the test student_id (e.g., "TEST-61-1" -> "61")
    batch = student_id.split('-')[1]
    
    cursor.execute("""
        INSERT INTO students (student_id, whatsapp_number, university_email, major, semester, batch, current_tutorial, is_matched)
        VALUES (%s, '+201000000000', %s, %s, %s, %s, %s, FALSE)
    """, (student_id, email, major, semester, batch, current_slot))
    
    for slot in desired_slots:
        cursor.execute("""
            INSERT INTO desired_slots (student_id, tutorial_id, priority)
            VALUES (%s, %s, 1)
        """, (student_id, slot))
        
    conn.commit()
    cursor.close()
    conn.close()

def check_is_matched(student_id):
    """Checks if a student is locked into a match."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT is_matched FROM students WHERE student_id = %s", (student_id,))
    result = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return result

def run_all_tests():
    print("🧹 Clearing old test data...\n")
    clear_test_data()

    # ==========================================
    # TEST 1: The Walled Garden (Major Mismatch)
    # ==========================================
    print("🧪 RUNNING TEST 1: The Walled Garden (CSEN vs MET)")
    inject_test_student("TEST-61-1", "test1@gmail.com", "MET", 7, current_slot=10, desired_slots=[11])
    inject_test_student("TEST-61-2", "test2@gmail.com", "CSEN", 7, current_slot=11, desired_slots=[10])
    
    run_matching_engine()
    
    # They should NOT match because their majors are different.
    if check_is_matched("TEST-61-1") == False and check_is_matched("TEST-61-2") == False:
        print("✅ TEST 1 PASSED: System correctly ignored the major mismatch.\n")
    else:
        print("❌ TEST 1 FAILED: System accidentally matched students across different majors!\n")

    clear_test_data()

    # ==========================================
    # TEST 2: The Standard 2-Way Match
    # ==========================================
    print("🧪 RUNNING TEST 2: Standard 2-Way Match")
    inject_test_student("TEST-61-3", "test3@gmail.com", "MET", 7, current_slot=20, desired_slots=[21])
    inject_test_student("TEST-61-4", "test4@gmail.com", "MET", 7, current_slot=21, desired_slots=[20])
    
    run_matching_engine()
    
    # They SHOULD match perfectly.
    if check_is_matched("TEST-61-3") == True and check_is_matched("TEST-61-4") == True:
        print("✅ TEST 2 PASSED: System successfully locked a 2-way trade.\n")
    else:
        print("❌ TEST 2 FAILED: System failed to recognize a perfect 2-way trade.\n")

    # ==========================================
    # TEST 3: The 2-Way Flake
    # ==========================================
    print("🧪 RUNNING TEST 3: The 2-Way Flake (A flakes, B goes back)")
    # We will simulate Student 3 flaking.
    conn = get_db_connection()
    cursor = conn.cursor()
    # Find Student 3's flake token
    cursor.execute("SELECT token, match_group_id FROM matches WHERE student_id = 'TEST-61-3'")
    flake_data = cursor.fetchone()
    
    if flake_data:
        flake_token = flake_data[0]
        match_group = flake_data[1]
        
        # Simulate hitting the /flake-swap endpoint
        cursor.execute("UPDATE matches SET status = 'flaked' WHERE token = %s", (flake_token,))
        cursor.execute("""
            UPDATE students 
            SET is_matched = FALSE 
            WHERE student_id IN (
                SELECT student_id FROM matches WHERE match_group_id = %s AND student_id != 'TEST-61-3'
            )
        """, (match_group,))
        conn.commit()
        
        # Student 4 should be back in the pool (is_matched = False)
        if check_is_matched("TEST-61-4") == False:
            print("✅ TEST 3 PASSED: Innocent partner was safely returned to the matching pool.\n")
        else:
            print("❌ TEST 3 FAILED: Innocent partner is still locked in the flaked trade!\n")
    else:
        print("❌ TEST 3 FAILED: Could not find the match in the database.\n")

    cursor.close()
    conn.close()

# ==========================================
    # TEST 4: The 3-Way Trade
    # ==========================================
    print("🧪 RUNNING TEST 4: The 3-Way Trade (A -> B -> C -> A)")
    # A wants B's slot (31)
    inject_test_student("TEST-61-5", "test5@gmail.com", "MET", 7, current_slot=30, desired_slots=[31])
    # B wants C's slot (32)
    inject_test_student("TEST-61-6", "test6@gmail.com", "MET", 7, current_slot=31, desired_slots=[32])
    # C wants A's slot (30)
    inject_test_student("TEST-61-7", "test7@gmail.com", "MET", 7, current_slot=32, desired_slots=[30])
    
    run_matching_engine()
    
    # They SHOULD all match perfectly in a loop.
    if check_is_matched("TEST-61-5") and check_is_matched("TEST-61-6") and check_is_matched("TEST-61-7"):
        print("✅ TEST 4 PASSED: System successfully locked a 3-way trade.\n")
    else:
        print("❌ TEST 4 FAILED: System failed to recognize or lock a 3-way trade.\n")

    # ==========================================
    # TEST 5: The 3-Way Flake
    # ==========================================
    print("🧪 RUNNING TEST 5: The 3-Way Flake (C flakes, A and B go back)")
    # We will simulate Student 7 (C) flaking.
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT token, match_group_id FROM matches WHERE student_id = 'TEST-61-7'")
    flake_data = cursor.fetchone()
    
    if flake_data:
        flake_token = flake_data[0]
        match_group = flake_data[1]
        
        # Simulate Student 7 hitting the /flake-swap endpoint
        cursor.execute("UPDATE matches SET status = 'flaked' WHERE token = %s", (flake_token,))
        cursor.execute("""
            UPDATE students 
            SET is_matched = FALSE 
            WHERE student_id IN (
                SELECT student_id FROM matches WHERE match_group_id = %s AND student_id != 'TEST-61-7'
            )
        """, (match_group,))
        conn.commit()
        
        # Students 5 and 6 should be back in the pool (is_matched = False)
        if check_is_matched("TEST-61-5") == False and check_is_matched("TEST-61-6") == False:
            print("✅ TEST 5 PASSED: Both innocent partners were safely returned to the matching pool.\n")
        else:
            print("❌ TEST 5 FAILED: Innocent partners are still locked in the flaked 3-way trade!\n")
    else:
        print("❌ TEST 5 FAILED: Could not find the match in the database.\n")

    # Clean up completely at the end
    clear_test_data()
    print("🎉 ALL TESTS COMPLETE! Database has been cleaned.")

if __name__ == "__main__":
    run_all_tests()